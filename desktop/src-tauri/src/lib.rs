//! Desktop shell and persistent local backend discovery.

mod daemon;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(daemon::DaemonState::default())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            daemon::ensure_backend,
            daemon::quit_workspace
        ])
        .run(tauri::generate_context!())
        .expect("error while running the Lgt shell");
}
