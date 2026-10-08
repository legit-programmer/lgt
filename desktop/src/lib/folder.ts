/** Pick a directory with the native dialog. Returns null when cancelled. */
export async function pickFolder(title: string, defaultPath?: string | null): Promise<string | null> {
  if (!("__TAURI_INTERNALS__" in window)) {
    // A plain browser has no folder dialog; the path is typed instead.
    const typed = window.prompt(`${title}\nEnter an absolute directory path:`, defaultPath ?? "");
    return typed?.trim() || null;
  }
  const { open } = await import("@tauri-apps/plugin-dialog");
  const picked = await open({ directory: true, multiple: false, title, defaultPath: defaultPath ?? undefined });
  return typeof picked === "string" ? picked : null;
}
