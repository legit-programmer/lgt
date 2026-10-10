//! Start or reconnect to the daemon without tying its lifetime to this window.

use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Manager, State};

const API_VERSION: u64 = 1;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);
const EXAMPLE_CONFIG: &str = include_str!("../../../config.example.json");

#[derive(Clone, Debug, Serialize)]
pub struct BackendConnection {
    pub url: String,
    pub token: Option<String>,
    pub managed: bool,
}

#[derive(Default)]
pub struct DaemonState {
    connection: Arc<Mutex<Option<BackendConnection>>>,
}

#[derive(Debug, Deserialize)]
struct Descriptor {
    pid: u32,
    port: u16,
    api_version: u64,
    token: String,
    started_at: String,
}

#[derive(Debug, Deserialize)]
struct Health {
    status: String,
    application: String,
    api_version: u64,
    pid: u32,
}

#[derive(Debug)]
enum HealthError {
    Unreachable,
    Failed(String),
}

impl std::fmt::Display for HealthError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unreachable => formatter.write_str("The backend is no longer listening"),
            Self::Failed(message) => formatter.write_str(message),
        }
    }
}

enum Discovery {
    Missing,
    Ready(BackendConnection),
    Incompatible(String),
}

struct WorkspacePaths {
    config: PathBuf,
    data: PathBuf,
}

#[tauri::command]
pub async fn ensure_backend(
    app: AppHandle,
    state: State<'_, DaemonState>,
) -> Result<BackendConnection, String> {
    let connection = Arc::clone(&state.connection);
    tauri::async_runtime::spawn_blocking(move || {
        let mut current = connection
            .lock()
            .map_err(|_| "Backend launch state is unavailable".to_string())?;
        let client = http_client()?;
        let result = ensure(&app, &client)?;
        *current = Some(result.clone());
        Ok(result)
    })
    .await
    .map_err(|error| format!("Backend launcher failed: {error}"))?
}

#[tauri::command]
pub async fn quit_workspace(app: AppHandle, state: State<'_, DaemonState>) -> Result<(), String> {
    let connection = Arc::clone(&state.connection);
    tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
        let mut current = connection
            .lock()
            .map_err(|_| "Backend launch state is unavailable".to_string())?;
        if let Some(connection) = current.as_ref().filter(|connection| connection.managed) {
            let client = http_client()?;
            stop_managed(&client, connection, Duration::from_secs(20))?;
        }
        *current = None;
        Ok(())
    })
    .await
    .map_err(|error| format!("Workspace shutdown failed: {error}"))??;
    app.exit(0);
    Ok(())
}

fn stop_managed(
    client: &Client,
    connection: &BackendConnection,
    timeout: Duration,
) -> Result<(), String> {
    match read_health(client, connection) {
        Err(HealthError::Unreachable) => return Ok(()),
        Err(error) => {
            return Err(format!(
                "Could not verify the workspace before shutdown: {error}"
            ));
        }
        Ok(health) if health.api_version != API_VERSION => {
            return Err("The workspace API changed. Quit its owning version of Lgt.".to_string());
        }
        Ok(_) => {}
    }
    let mut request = client.post(format!("{}/shutdown", connection.url));
    if let Some(token) = &connection.token {
        request = request.bearer_auth(token);
    }
    request
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| format!("Could not shut down the workspace: {error}"))?;
    let deadline = Instant::now() + timeout;
    loop {
        let verification_error = match read_health(client, connection) {
            Err(HealthError::Unreachable) => return Ok(()),
            Err(error) => Some(error.to_string()),
            Ok(_) => None,
        };
        if Instant::now() >= deadline {
            if let Some(error) = verification_error {
                return Err(format!(
                    "Could not confirm workspace shutdown: {error}. Try Quit Lgt again."
                ));
            }
            return Err("The workspace is still shutting down. Try Quit Lgt again.".to_string());
        }
        thread::sleep(Duration::from_millis(200));
    }
}

fn http_client() -> Result<Client, String> {
    Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(4))
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|error| format!("Could not initialize backend discovery: {error}"))
}

fn validate_url(value: &str) -> Result<String, String> {
    let url = url::Url::parse(value.trim())
        .map_err(|_| "LGT_BACKEND_URL must be a loopback HTTP URL".to_string())?;
    let loopback = match url.host() {
        Some(url::Host::Ipv4(ip)) => ip.is_loopback(),
        Some(url::Host::Ipv6(ip)) => ip.is_loopback(),
        Some(url::Host::Domain(domain)) => domain.eq_ignore_ascii_case("localhost"),
        None => false,
    };
    if !loopback
        || url.scheme() != "http"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
    {
        return Err(
            "LGT_BACKEND_URL must be a loopback HTTP origin without credentials or a path"
                .to_string(),
        );
    }
    Ok(url.as_str().trim_end_matches('/').to_string())
}

fn read_health(client: &Client, connection: &BackendConnection) -> Result<Health, HealthError> {
    let mut request = client.get(format!("{}/health", connection.url));
    if let Some(token) = &connection.token {
        request = request.bearer_auth(token);
    }
    let health: Health = request
        .send()
        .and_then(|response| response.error_for_status())
        .and_then(|response| response.json())
        .map_err(|error| {
            if error.is_connect() && !error.is_timeout() {
                HealthError::Unreachable
            } else {
                HealthError::Failed(error.to_string())
            }
        })?;
    if health.application != "lgt" || health.status != "ok" || health.pid == 0 {
        return Err(HealthError::Failed(
            "The process at this address is not a ready Lgt backend".to_string(),
        ));
    }
    Ok(health)
}

fn parse_descriptor(bytes: &[u8]) -> Result<Descriptor, String> {
    let descriptor: Descriptor =
        serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    if descriptor.pid == 0
        || descriptor.port == 0
        || descriptor.token.len() < 32
        || descriptor.token.len() > 512
        || descriptor.token.chars().any(char::is_control)
        || descriptor.started_at.is_empty()
    {
        return Err("Invalid daemon descriptor".to_string());
    }
    Ok(descriptor)
}

fn discover(client: &Client, path: &Path) -> Discovery {
    let Ok(bytes) = fs::read(path) else {
        return Discovery::Missing;
    };
    let Ok(descriptor) = parse_descriptor(&bytes) else {
        return Discovery::Missing;
    };
    let connection = BackendConnection {
        url: format!("http://127.0.0.1:{}", descriptor.port),
        token: Some(descriptor.token),
        managed: true,
    };
    let Ok(health) = read_health(client, &connection) else {
        return Discovery::Missing;
    };
    if health.pid != descriptor.pid {
        // A reused port or PID is insufficient proof of ownership. Never kill it.
        return Discovery::Missing;
    }
    if health.api_version != API_VERSION || descriptor.api_version != API_VERSION {
        return Discovery::Incompatible(format!(
            "A different Lgt backend API is already using this workspace (API {}). Quit that version before reopening Lgt.",
            health.api_version
        ));
    }
    Discovery::Ready(connection)
}

fn ensure(app: &AppHandle, client: &Client) -> Result<BackendConnection, String> {
    if let Ok(value) = std::env::var("LGT_BACKEND_URL") {
        let connection = BackendConnection {
            url: validate_url(&value)?,
            token: std::env::var("LGT_BACKEND_TOKEN")
                .ok()
                .filter(|token| !token.is_empty()),
            managed: false,
        };
        let health = read_health(client, &connection).map_err(|error| {
            format!("The backend specified by LGT_BACKEND_URL is unavailable: {error}")
        })?;
        if health.api_version != API_VERSION {
            return Err(format!(
                "Lgt requires backend API {API_VERSION}, but this server provides {}",
                health.api_version
            ));
        }
        return Ok(connection);
    }
    let paths = workspace_paths(app)?;
    let descriptor = paths.data.join("daemon.json");
    match discover(client, &descriptor) {
        Discovery::Ready(connection) => return Ok(connection),
        Discovery::Incompatible(error) => return Err(error),
        Discovery::Missing => {}
    }
    let logs = paths.data.join("logs");
    fs::create_dir_all(&logs)
        .map_err(|error| format!("Could not create workspace logs: {error}"))?;
    let log_path = logs.join("daemon.log");
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| format!("Could not open {}: {error}", log_path.display()))?;
    let mut command = backend_command(app)?;
    command
        .arg("--config")
        .arg(&paths.config)
        .args(["--port", "0", "--daemon"]);
    launch_and_wait(
        client,
        &descriptor,
        command,
        log,
        &log_path,
        STARTUP_TIMEOUT,
    )
}

fn launch_and_wait(
    client: &Client,
    descriptor: &Path,
    mut command: Command,
    log: std::fs::File,
    log_path: &Path,
    timeout: Duration,
) -> Result<BackendConnection, String> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::from(
            log.try_clone().map_err(|error| error.to_string())?,
        ))
        .stderr(Stdio::from(log));
    let mut child = spawn_detached(&mut command).map_err(|error| {
        format!(
            "Could not launch the Lgt backend: {error}. Log: {}",
            log_path.display()
        )
    })?;
    let deadline = Instant::now() + timeout;
    let mut exit_description = None;
    loop {
        match discover(client, descriptor) {
            Discovery::Ready(connection) => {
                reap(child);
                return Ok(connection);
            }
            Discovery::Incompatible(error) => {
                reap(child);
                return Err(error);
            }
            Discovery::Missing => {}
        }
        if exit_description.is_none() {
            if let Some(status) = child.try_wait().map_err(|error| error.to_string())? {
                exit_description = Some(status.to_string());
            }
        }
        // A competing launcher may own workspace.lock but not yet be ready.
        // Give it the readiness window; lock failure is not a dead daemon.
        if Instant::now() >= deadline {
            reap(child);
            let detail = exit_description
                .map(|status| format!("Backend exited with {status}."))
                .unwrap_or_else(|| {
                    format!(
                        "The backend did not become ready within {} seconds.",
                        timeout.as_secs()
                    )
                });
            return Err(format!(
                "{detail} Inspect {} and retry.",
                log_path.display()
            ));
        }
        thread::sleep(Duration::from_millis(250));
    }
}

fn reap(mut child: Child) {
    thread::spawn(move || {
        let _ = child.wait();
    });
}

fn workspace_paths(app: &AppHandle) -> Result<WorkspacePaths, String> {
    let config = if let Ok(value) = std::env::var("LGT_CONFIG") {
        let path = PathBuf::from(value);
        if !path.is_absolute() {
            return Err("LGT_CONFIG must be an absolute configuration path".to_string());
        }
        path
    } else {
        let development_config = repository_root().join("config.local.json");
        if cfg!(debug_assertions) && development_config.is_file() {
            development_config
        } else {
            let directory = app
                .path()
                .app_config_dir()
                .map_err(|error| error.to_string())?;
            fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
            let path = directory.join("backend.json");
            if !path.exists() {
                let data = app
                    .path()
                    .app_data_dir()
                    .map_err(|error| error.to_string())?;
                let mut value: Value =
                    serde_json::from_str(EXAMPLE_CONFIG).map_err(|error| error.to_string())?;
                value["settings"]["data_dir"] = serde_json::json!(data);
                value["settings"]["allowed_origins"] = serde_json::json!([
                    "http://tauri.localhost",
                    "tauri://localhost",
                    "http://localhost:1420",
                    "http://localhost"
                ]);
                write_new_config(&path, &value)?;
            }
            path
        }
    };
    let config = fs::canonicalize(&config).map_err(|error| {
        format!(
            "Could not read backend config {}: {error}",
            config.display()
        )
    })?;
    let value: Value =
        serde_json::from_slice(&fs::read(&config).map_err(|error| error.to_string())?)
            .map_err(|error| format!("Invalid backend configuration: {error}"))?;
    let data = value["settings"]["data_dir"]
        .as_str()
        .ok_or("Backend config requires settings.data_dir")?;
    let home = app.path().home_dir().map_err(|error| error.to_string())?;
    let data = resolve_data_path(data, config.parent().unwrap(), &home)?;
    Ok(WorkspacePaths { config, data })
}

fn resolve_data_path(value: &str, config_directory: &Path, home: &Path) -> Result<PathBuf, String> {
    if value.trim().is_empty() {
        return Err("settings.data_dir cannot be empty".to_string());
    }
    let path = if value == "~" {
        home.to_path_buf()
    } else if let Some(rest) = value
        .strip_prefix("~/")
        .or_else(|| value.strip_prefix("~\\"))
    {
        home.join(rest)
    } else if value.starts_with('~') {
        return Err("settings.data_dir must use ~ or ~/ for home paths".to_string());
    } else {
        PathBuf::from(value)
    };
    Ok(if path.is_absolute() {
        path
    } else {
        config_directory.join(path)
    })
}

fn write_new_config(path: &Path, value: &Value) -> Result<(), String> {
    // Link a complete file atomically, without overwriting another instance's config.
    let temporary = path.with_extension(format!("{}.tmp", std::process::id()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .map_err(|error| error.to_string())?;
    let result = (|| {
        file.write_all(&serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
        drop(file);
        match fs::hard_link(&temporary, path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => Ok(()),
            Err(error) => Err(format!(
                "Could not create desktop backend configuration: {error}"
            )),
        }
    })();
    let _ = fs::remove_file(temporary);
    result
}

fn repository_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."))
}

fn backend_command(app: &AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        let root = repository_root();
        let python = root.join(if cfg!(windows) {
            ".venv/Scripts/python.exe"
        } else {
            ".venv/bin/python"
        });
        let mut command = if python.is_file() {
            let mut command = Command::new(python);
            command.args(["-m", "lgt"]);
            command
        } else {
            let mut command = Command::new("uv");
            command
                .arg("run")
                .arg("--project")
                .arg(&root)
                .args(["python", "-m", "lgt"]);
            command
        };
        command.current_dir(&root);
        Ok(command)
    } else {
        let runtime = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?
            .join("backend");
        let python = runtime.join(if cfg!(windows) {
            "python.exe"
        } else {
            "bin/python3"
        });
        if !python.is_file() {
            return Err(
                "This Lgt installation is missing its bundled backend. Reinstall the application."
                    .to_string(),
            );
        }
        let mut command = Command::new(python);
        command.args(["-m", "lgt"]).current_dir(&runtime);
        Ok(command)
    }
}

#[cfg(windows)]
fn spawn_detached(command: &mut Command) -> std::io::Result<Child> {
    use std::os::windows::process::CommandExt;
    const HIDDEN_GROUP: u32 = 0x0800_0000 | 0x0000_0200;
    // Escape inherited jobs when the launcher allows it. Restricted development
    // hosts can deny breakaway; those hosts still control descendant lifetime.
    command.creation_flags(HIDDEN_GROUP | 0x0100_0000);
    match command.spawn() {
        Err(error) if error.raw_os_error() == Some(5) => {
            command.creation_flags(HIDDEN_GROUP);
            command.spawn()
        }
        result => result,
    }
}

#[cfg(unix)]
fn spawn_detached(command: &mut Command) -> std::io::Result<Child> {
    use std::os::unix::process::CommandExt;
    unsafe {
        command.pre_exec(|| {
            if libc::setsid() == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    command.spawn()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Read, Write},
        net::TcpListener,
    };

    fn health_server(pid: u32, api_version: u64) -> (u16, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            let (mut connection, _) = listener.accept().unwrap();
            connection
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut buffer = [0u8; 4096];
            let size = connection.read(&mut buffer).unwrap();
            let request = String::from_utf8_lossy(&buffer[..size]).to_ascii_lowercase();
            assert!(request.contains("get /health "));
            assert!(request.contains(&format!("authorization: bearer {}", "a".repeat(64))));
            let body = serde_json::json!({"status": "ok", "application": "lgt", "api_version": api_version, "pid": pid}).to_string();
            write!(connection, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body).unwrap();
        });
        (port, server)
    }

    #[test]
    fn discovery_verifies_the_serving_identity_and_rejects_stale_metadata() {
        let client = http_client().unwrap();
        let path =
            std::env::temp_dir().join(format!("lgt-descriptor-test-{}.json", std::process::id()));
        for (pid, version, expected) in
            [(42, 1, "ready"), (99, 1, "stale"), (42, 2, "incompatible")]
        {
            let (port, server) = health_server(pid, version);
            let descriptor = serde_json::json!({ "pid": 42, "port": port, "api_version": 1,
                "token": "a".repeat(64), "started_at": "2026-10-10T00:00:00Z" });
            fs::write(&path, serde_json::to_vec(&descriptor).unwrap()).unwrap();
            let result = discover(&client, &path);
            assert!(matches!(
                (expected, result),
                ("ready", Discovery::Ready(_))
                    | ("stale", Discovery::Missing)
                    | ("incompatible", Discovery::Incompatible(_))
            ));
            server.join().unwrap();
        }
        fs::write(&path, b"truncated metadata").unwrap();
        assert!(matches!(discover(&client, &path), Discovery::Missing));
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn launcher_replaces_stale_discovery_and_reuses_a_detached_server() {
        let directory =
            std::env::temp_dir().join(format!("lgt-launch-test-{}", std::process::id()));
        fs::create_dir_all(&directory).unwrap();
        let descriptor = directory.join("daemon.json");
        let script = directory.join("fake-daemon.py");
        fs::write(&descriptor, b"stale descriptor").unwrap();
        fs::write(&script, r#"
import http.server, json, os, pathlib, sys, threading
descriptor = pathlib.Path(sys.argv[1])
token = 'a' * 64
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def reply(self, body):
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
    def do_GET(self):
        assert self.headers.get('Authorization') == 'Bearer ' + token
        self.reply({'status':'ok','application':'lgt','api_version':1,'pid':os.getpid()})
    def do_POST(self):
        assert self.headers.get('Authorization') == 'Bearer ' + token
        self.reply({'status':'stopping'})
        threading.Thread(target=server.shutdown).start()
server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
descriptor.write_text(json.dumps({'pid':os.getpid(),'port':server.server_port,'api_version':1,'token':token,'started_at':'test'}))
try: server.serve_forever()
finally:
    server.server_close()
    descriptor.unlink(missing_ok=True)
"#).unwrap();
        let python = repository_root().join(if cfg!(windows) {
            ".venv/Scripts/python.exe"
        } else {
            ".venv/bin/python"
        });
        let mut command = Command::new(python);
        command.arg(&script).arg(&descriptor);
        let log_path = directory.join("daemon.log");
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .unwrap();
        let client = http_client().unwrap();
        let connection = launch_and_wait(
            &client,
            &descriptor,
            command,
            log,
            &log_path,
            Duration::from_secs(10),
        )
        .unwrap();
        let Discovery::Ready(reused) = discover(&client, &descriptor) else {
            panic!("daemon was not reusable")
        };
        assert_eq!(reused.url, connection.url);
        assert_eq!(reused.token, connection.token);
        stop_managed(&client, &connection, Duration::from_secs(5)).unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while descriptor.exists() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(50));
        }
        assert!(!descriptor.exists(), "fake daemon failed to shut down");
        fs::remove_file(script).unwrap();
        fs::remove_file(log_path).unwrap();
        fs::remove_dir(directory).unwrap();
    }
    #[test]
    fn backend_override_requires_a_loopback_origin() {
        for value in [
            "http://127.0.0.1:9000/",
            "http://localhost:8000",
            "http://[::1]:8000",
        ] {
            assert!(validate_url(value).is_ok(), "{value}");
        }
        for value in [
            "https://example.org",
            "http://example.org",
            "http://127.0.0.1/path",
            "http://user@localhost",
            "http://localhost?token=secret",
            "file:///tmp/server",
        ] {
            assert!(validate_url(value).is_err(), "{value}");
        }
    }

    #[test]
    fn shutdown_does_not_treat_failed_verification_as_a_stopped_server() {
        for status in ["401 Unauthorized", "503 Service Unavailable"] {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let port = listener.local_addr().unwrap().port();
            let server = thread::spawn(move || {
                let (mut stream, _) = listener.accept().unwrap();
                let mut buffer = [0; 4096];
                stream.read(&mut buffer).unwrap();
                write!(
                    stream,
                    "HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                .unwrap();
            });
            let connection = BackendConnection {
                url: format!("http://127.0.0.1:{port}"),
                token: Some("test-token".into()),
                managed: true,
            };
            assert!(
                stop_managed(&http_client().unwrap(), &connection, Duration::ZERO)
                    .unwrap_err()
                    .contains("before shutdown")
            );
            server.join().unwrap();
            // Refused connection after the verified failure is a distinct state.
            assert!(stop_managed(&http_client().unwrap(), &connection, Duration::ZERO).is_ok());
        }
    }

    #[test]
    fn shutdown_requires_connection_refusal_after_a_successful_stop_request() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            for step in 0..3 {
                let (mut stream, _) = listener.accept().unwrap();
                let mut buffer = [0; 4096];
                let size = stream.read(&mut buffer).unwrap();
                let request = String::from_utf8_lossy(&buffer[..size]);
                let (status, body) = match step {
                    0 => (
                        "200 OK",
                        r#"{"status":"ok","application":"lgt","api_version":1,"pid":42}"#,
                    ),
                    1 => {
                        assert!(request.starts_with("POST /shutdown "));
                        ("200 OK", r#"{"status":"stopping"}"#)
                    }
                    _ => ("401 Unauthorized", "{}"),
                };
                write!(stream, "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
            }
        });
        let connection = BackendConnection {
            url: format!("http://127.0.0.1:{port}"),
            token: Some("test-token".into()),
            managed: true,
        };
        assert!(
            stop_managed(&http_client().unwrap(), &connection, Duration::ZERO)
                .unwrap_err()
                .contains("confirm workspace shutdown")
        );
        server.join().unwrap();
    }
    #[test]
    fn descriptor_requires_a_valid_pid_port_and_token() {
        let valid = serde_json::json!({ "pid": 10, "port": 3456, "api_version": 1,
            "token": "a".repeat(64), "started_at": "2026-10-10T00:00:00Z" });
        assert!(parse_descriptor(&serde_json::to_vec(&valid).unwrap()).is_ok());
        for (key, value) in [
            ("pid", serde_json::json!(0)),
            ("port", serde_json::json!(0)),
            ("token", serde_json::json!("short")),
            ("started_at", serde_json::json!("")),
        ] {
            let mut invalid = valid.clone();
            invalid[key] = value;
            assert!(parse_descriptor(&serde_json::to_vec(&invalid).unwrap()).is_err());
        }
        assert!(parse_descriptor(b"not json").is_err());
    }
    #[test]
    fn relative_and_home_data_paths_match_backend_resolution() {
        let base = std::env::temp_dir().join("config");
        let home = std::env::temp_dir().join("home");
        assert_eq!(
            resolve_data_path("workspace", &base, &home).unwrap(),
            base.join("workspace")
        );
        assert_eq!(
            resolve_data_path("~/.lgt", &base, &home).unwrap(),
            home.join(".lgt")
        );
        assert!(resolve_data_path("", &base, &home).is_err());
    }
    #[test]
    fn existing_configuration_is_never_overwritten() {
        let path =
            std::env::temp_dir().join(format!("lgt-config-test-{}.json", std::process::id()));
        let _ = fs::remove_file(&path);
        write_new_config(&path, &serde_json::json!({"original": true})).unwrap();
        write_new_config(&path, &serde_json::json!({"replacement": true})).unwrap();
        let value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(value, serde_json::json!({"original": true}));
        fs::remove_file(path).unwrap();
    }
}
