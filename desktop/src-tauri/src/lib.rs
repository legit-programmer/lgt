//! Lgt desktop shell.
//!
//! The shell hosts the UI and connects to an already running Lgt backend.
//! It does not own the backend's lifecycle yet: the daemon handshake it would
//! need (port file, launch token, shutdown, API version) is listed in
//! design/backend-gaps.md.

const DEFAULT_BACKEND_URL: &str = "http://127.0.0.1:8000";

/// The backend base URL, from `LGT_BACKEND_URL` or the documented default.
#[tauri::command]
fn backend_url() -> String {
    std::env::var("LGT_BACKEND_URL")
        .ok()
        .map(|value| value.trim().trim_end_matches('/').to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| DEFAULT_BACKEND_URL.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![backend_url])
        .run(tauri::generate_context!())
        .expect("error while running the Lgt shell");
}
