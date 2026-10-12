import { useEffect, useState } from "react";
import { fetchBackendResource } from "../api/client";
import { useWorkspace } from "../store/workspace";
import { isAndroid, isMobile } from "./platform";

/*
 * Attachment bytes are fetched with CORS from the window's allowed origin and
 * shown as blob URLs. Plain <img> and download navigations carry no Origin
 * header, so the backend's local-origin policy rejects them as cross-site.
 */

const cache = new Map<string, Promise<string>>();

export function fetchBlobUrl(url: string): Promise<string> {
  let pending = cache.get(url);
  if (!pending) {
    pending = fetchBackendResource(url, { mode: "cors" }).then(async (response) => {
      if (!response.ok) throw new Error(`Could not load the attachment (${response.status}).`);
      return URL.createObjectURL(await response.blob());
    });
    pending.catch(() => cache.delete(url));
    cache.set(url, pending);
  }
  return pending;
}

export function useBlobUrl(url: string | null): { src: string | null; failed: boolean } {
  const [state, setState] = useState<{ src: string | null; failed: boolean }>({ src: null, failed: false });
  useEffect(() => {
    if (!url) return;
    let live = true;
    fetchBlobUrl(url)
      .then((src) => live && setState({ src, failed: false }))
      .catch(() => live && setState({ src: null, failed: true }));
    return () => {
      live = false;
    };
  }, [url]);
  return state;
}

/** Save an attachment through a blob URL with its original filename. */
export async function downloadAttachment(url: string, filename: string): Promise<void> {
  if (isMobile) return saveOnDevice(url, filename);
  const href = await fetchBlobUrl(url);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/** A server-supplied name as a single safe path segment. */
export function safeFilename(name: string): string {
  const cleaned = name.replace(/[\u0000-\u001f/\\:]/g, "_").trim();
  return cleaned && cleaned !== "." && cleaned !== ".." ? cleaned : "attachment";
}

/** `report.pdf`, then `report (1).pdf`, `report (2).pdf`… until `taken` is false. */
export async function freeFilename(name: string, taken: (candidate: string) => Promise<boolean>): Promise<string> {
  const dot = name.lastIndexOf(".");
  const [stem, extension] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""];
  let candidate = name;
  for (let copy = 1; await taken(candidate); copy += 1) candidate = `${stem} (${copy})${extension}`;
  return candidate;
}

/*
 * Mobile webviews ignore <a download>. Android saves through the system file
 * picker. On iOS the plugin's save dialog only exports an empty placeholder,
 * so files go to the app's Documents folder, which Files shows under Lgt.
 */
async function saveOnDevice(url: string, filename: string): Promise<void> {
  const response = await fetchBackendResource(url, { mode: "cors" });
  if (!response.ok) throw new Error(`Could not load the attachment (${response.status}).`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  const name = safeFilename(filename);
  const { BaseDirectory, exists, writeFile } = await import("@tauri-apps/plugin-fs");
  if (isAndroid) {
    const { save } = await import("@tauri-apps/plugin-dialog");
    const target = await save({ defaultPath: name });
    if (target) await writeFile(target, bytes);
    return;
  }
  const saved = await freeFilename(name, (candidate) => exists(candidate, { baseDir: BaseDirectory.Document }));
  await writeFile(saved, bytes, { baseDir: BaseDirectory.Document });
  useWorkspace.getState().toast(`Saved ${saved} to Files › Lgt.`, "info");
}
