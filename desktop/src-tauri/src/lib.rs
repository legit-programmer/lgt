//! Desktop shell and persistent local backend discovery.
//!
//! Mobile builds are paired clients only: a phone hosts no workspace, so the
//! daemon launcher and its commands exist on desktop alone.

#[cfg(desktop)]
mod daemon;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init());

    #[cfg(desktop)]
    let builder = builder
        .manage(daemon::DaemonState::default())
        .invoke_handler(tauri::generate_handler![
            daemon::ensure_backend,
            daemon::quit_workspace,
            daemon::quit_client
        ]);

    #[cfg(mobile)]
    let builder = builder
        .plugin(tauri_plugin_barcode_scanner::init())
        .plugin(tauri_plugin_fs::init());

    builder
        .run(tauri::generate_context!())
        .expect("error while running the Lgt shell");
}
