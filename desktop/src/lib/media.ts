import { useEffect, useState } from "react";
import { fetchBackendResource } from "../api/client";

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
  const href = await fetchBlobUrl(url);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}
