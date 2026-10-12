import { isRemoteConnection } from "../api/client";
import { requestPath } from "../components/PathPrompt";

/** Pick a directory with the native dialog. Returns null when cancelled. */
export async function pickFolder(title: string, defaultPath?: string | null): Promise<string | null> {
  if (isRemoteConnection() || !("__TAURI_INTERNALS__" in window)) {
    // The native dialog would browse this device, not the workspace host; the path is typed instead.
    return requestPath(title, defaultPath);
  }
  const { open } = await import("@tauri-apps/plugin-dialog");
  const picked = await open({ directory: true, multiple: false, title, defaultPath: defaultPath ?? undefined });
  return typeof picked === "string" ? picked : null;
}
