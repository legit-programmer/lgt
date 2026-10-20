import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy, type RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { api } from "../../api/client";

GlobalWorkerOptions.workerSrc = workerUrl;

export default function PdfArtefact({ channelId, path }: { channelId: string; path: string }) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(600);
  const [error, setError] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    let task: ReturnType<typeof getDocument> | undefined;
    void (async () => {
      try {
        const data = await (await api.artefactContent(channelId, path, controller.signal)).arrayBuffer();
        if (controller.signal.aborted) return;
        const assets = new URL("./pdfjs/", document.baseURI).href;
        task = getDocument({ data, cMapUrl: `${assets}cmaps/`, cMapPacked: true,
          standardFontDataUrl: `${assets}standard_fonts/`, wasmUrl: `${assets}wasm/` });
        const loaded = await task.promise;
        if (!controller.signal.aborted) setPdf(loaded);
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
      }
    })();
    return () => { controller.abort(); void task?.destroy(); };
  }, [channelId, path]);
  useEffect(() => {
    if (!viewport.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(100, entry.contentRect.width - 32)));
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let cancelled = false;
    let render: RenderTask | undefined;
    if (!pdf || !canvas.current) return;
    const target = canvas.current;
    void (async () => {
      try {
        const documentPage = await pdf.getPage(page);
        if (cancelled) return;
        const natural = documentPage.getViewport({ scale: 1 });
        const scale = width / natural.width * zoom;
        const ratio = window.devicePixelRatio || 1;
        const view = documentPage.getViewport({ scale: scale * ratio });
        target.width = Math.ceil(view.width);
        target.height = Math.ceil(view.height);
        target.style.width = `${view.width / ratio}px`;
        target.style.height = `${view.height / ratio}px`;
        render = documentPage.render({ canvas: target, viewport: view });
        await render.promise;
      } catch (failure) {
        if (!cancelled) setError(failure instanceof Error ? failure.message : String(failure));
      }
    })();
    return () => { cancelled = true; render?.cancel(); };
  }, [pdf, page, zoom, width]);
  return <div className="artefact-pdf">
    <div className="artefacts-toolbar">
      <button className="fv-icon-btn" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft /></button>
      <span className="fv-meta" aria-live="polite">Page {page} of {pdf?.numPages ?? "…"}</span>
      <button className="fv-icon-btn" aria-label="Next page" disabled={!pdf || page >= pdf.numPages} onClick={() => setPage((p) => p + 1)}><ChevronRight /></button>
      <span className="artefacts-spacer" />
      <button className="fv-icon-btn" aria-label="Zoom out" disabled={zoom <= 0.5} onClick={() => setZoom((z) => z - 0.25)}><Minus /></button>
      <span className="fv-meta">{Math.round(zoom * 100)}%</span>
      <button className="fv-icon-btn" aria-label="Zoom in" disabled={zoom >= 3} onClick={() => setZoom((z) => z + 0.25)}><Plus /></button>
    </div>
    {error ? <p className="artefact-notice" role="alert">{error}</p> : null}
    {!pdf && !error ? <p className="artefact-notice" role="status">Loading PDF…</p> : null}
    <div className="artefact-pdf-pages" ref={viewport}><canvas ref={canvas} aria-label={`PDF page ${page}`} role="img" /></div>
  </div>;
}
