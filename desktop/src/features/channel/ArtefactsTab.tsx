import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileCode, FileText, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { api, assetUrl } from "../../api/client";
import type { Artefact, ChannelSummary } from "../../api/types";
import { Markdown } from "../../components/Markdown";
import { useUi } from "../../store/ui";
import { reportError, useWorkspace } from "../../store/workspace";

const PdfArtefact = lazy(() => import("./PdfArtefact"));
const noHandles = new Set<string>();
const noAgents = {};

export function ArtefactsTab({ channel }: { channel: ChannelSummary }) {
  const revision = useWorkspace((s) => s.artefactRevision);
  const selection = useUi((s) => s.selectedArtefact);
  const [refresh, setRefresh] = useState(0);
  const [action, setAction] = useState<"rename" | "delete" | null>(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const files = useQuery({
    queryKey: ["artefacts", channel.channel_id, channel.cwd, revision],
    queryFn: () => api.artefacts(channel.channel_id),
    refetchInterval: 3000,
  });
  const selectedPath = selection?.channelId === channel.channel_id && selection.cwd === channel.cwd ? selection.path : null;
  const selected = files.data?.find((file) => file.path === selectedPath);
  const mutate = async () => {
    if (!selected || !action) return;
    setSaving(true);
    try {
      if (action === "rename") await api.renameArtefact(channel.channel_id, selected.path, name.trim());
      else await api.deleteArtefact(channel.channel_id, selected.path);
      setAction(null);
      await files.refetch();
    } catch (error) { reportError(error); }
    finally { setSaving(false); }
  };
  return <div className="artefacts">
    <div className="artefacts-toolbar">
      {selectedPath ? <button className="fv-icon-btn" aria-label="All artefacts" onClick={() => useUi.getState().clearArtefact()}><ArrowLeft /></button> : null}
      <span className="artefacts-title" title={selected?.path}>{selected?.name ?? "Channel artefacts"}</span>
      <button className="fv-icon-btn" aria-label="Refresh artefacts" onClick={() => { setRefresh((n) => n + 1); void files.refetch(); }}><RefreshCw /></button>
      {selected ? <>
        <button className="fv-icon-btn" aria-label="Rename artefact" onClick={() => { setName(selected.name); setAction("rename"); }}><Pencil /></button>
        <button className="fv-icon-btn" aria-label="Delete artefact" onClick={() => setAction("delete")}><Trash2 /></button>
      </> : null}
    </div>
    {files.isError ? <p className="artefact-notice" role="alert">{files.error.message}</p>
      : files.isPending ? <p className="artefact-notice" role="status">Loading artefacts…</p>
      : selected ? <ArtefactView key={`${channel.cwd}:${selected.path}:${selected.revision}:${selection?.generation}:${refresh}`} channelId={channel.channel_id} artefact={selected} />
      : selectedPath ? <p className="artefact-notice" role="status">This artefact is no longer in this channel’s folder. It may have been renamed or moved. Open All artefacts to find available files.</p>
      : <div className="artefact-list">
        {!files.data?.length ? <div className="artefact-empty"><FileText /><h2>No artefacts yet</h2><p>Ask an agent to create a plan, document, PDF or interactive visualisation. Files saved for this channel appear here.</p></div> : null}
        {files.data?.map((file) => <button className="artefact-row" key={file.path} onClick={() => useUi.getState().openArtefact(channel.channel_id, channel.cwd, file.path)}>
          {file.kind === "html" ? <FileCode /> : <FileText />}
          <span><strong>{file.name}</strong><small className="fv-meta">{file.path !== file.name ? `${file.path} · ` : ""}{file.kind === "markdown" ? "Markdown" : file.kind.toUpperCase()} · {Math.max(1, Math.round(file.size_bytes / 1024))} KB</small></span>
        </button>)}
      </div>}
    <Dialog.Root open={action !== null} onOpenChange={(open) => { if (!open && !saving) setAction(null); }}>
      <Dialog.Portal><Dialog.Overlay className="fv-dialog-overlay" /><Dialog.Content className="fv-dialog fv-glass">
        <Dialog.Title className="fv-dialog-title">{action === "rename" ? "Rename artefact" : "Delete artefact"}</Dialog.Title>
        <Dialog.Description className="fv-dialog-desc">{action === "rename" ? "Keep the file extension. This renames the file on disk." : `Delete ${selected?.name ?? "this file"} from disk? This cannot be undone.`}</Dialog.Description>
        <form className="fv-field" onSubmit={(event) => { event.preventDefault(); void mutate(); }}>
          {action === "rename" ? <><label htmlFor="artefact-name">Filename</label><input id="artefact-name" className="fv-input" value={name} onChange={(event) => setName(event.target.value)} /></> : null}
          <div className="fv-dialog-actions">
            <button type="button" className="fv-btn fv-btn--ghost" disabled={saving} onClick={() => setAction(null)}>Cancel</button>
            <button className={`fv-btn ${action === "delete" ? "fv-btn--danger" : "fv-btn--primary"}`} disabled={saving || !selected || (action === "rename" && (!name.trim() || name.trim() === selected.name))}>{saving ? "Saving…" : action === "rename" ? "Rename" : "Delete"}</button>
          </div>
        </form>
      </Dialog.Content></Dialog.Portal>
    </Dialog.Root>
  </div>;
}

function ArtefactView({ channelId, artefact }: { channelId: string; artefact: Artefact }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    if (artefact.kind === "pdf") return () => controller.abort();
    void (async () => {
      try {
        const value = artefact.kind === "html"
          ? assetUrl((await api.artefactPreview(channelId, artefact.path)).url)
          : await (await api.artefactContent(channelId, artefact.path, controller.signal)).text();
        if (!controller.signal.aborted) setContent(value);
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
      }
    })();
    return () => controller.abort();
  }, [channelId, artefact.kind, artefact.path]);
  if (error) return <p className="artefact-notice" role="alert">{error}</p>;
  if (artefact.kind === "pdf") return <Suspense fallback={<p className="artefact-notice">Loading PDF viewer…</p>}><PdfArtefact channelId={channelId} path={artefact.path} /></Suspense>;
  if (content === null) return <p className="artefact-notice" role="status">Loading preview…</p>;
  if (artefact.kind === "html") return <iframe className="artefact-html" title={artefact.name} src={content} sandbox="allow-scripts" referrerPolicy="no-referrer" />;
  return <article className="artefact-markdown fv-markdown"><Markdown text={content} handles={noHandles} agents={noAgents} /></article>;
}
