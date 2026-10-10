import { ProviderLogo } from "../../components/ProviderLogo";
import { useState } from "react";
import {
  ArrowRight, Ban, Bookmark, ChevronDown, ChevronRight, Clock, CornerDownLeft, FileText, Folder,
  Hash, RotateCcw, Square, UserMinus, UserPlus, X,
} from "lucide-react";
import { api } from "../../api/client";
import type {
  Agent, AttachmentSummary, RoutingPayload, RunStatusPayload, ToolCallPayload, ToolResultPayload,
  WorkspaceEvent,
} from "../../api/types";
import { AgentAvatar, PersonAvatar } from "../../components/Avatar";
import { Markdown } from "../../components/Markdown";
import { Elapsed, StatusBadge, WorkingDots } from "../../components/Status";
import { harnessLabel, hueStyle } from "../../lib/agents";
import { bytes, clockTime, dayTime, displayPath, duration } from "../../lib/format";
import { toolGroupSummary, toolName, type HumanBlock, type RunBlock, type ToolEntry } from "../../lib/timeline";
import { downloadAttachment, useBlobUrl } from "../../lib/media";
import { reportError, useWorkspace, type RunInfo } from "../../store/workspace";

export interface BlockContext {
  channelId: string;
  agents: Record<string, Agent>;
  memberIds: ReadonlySet<string>;
  handles: ReadonlySet<string>;
  displayName: string;
  runs: Record<string, RunInfo>;
}

function AgentChip({ agent, fallback }: { agent: Agent | undefined; fallback?: string }) {
  return (
    <span className="fv-chip" style={hueStyle(agent)}>
      <AgentAvatar agent={agent} className="chip-avatar" />
      {agent?.handle ?? fallback ?? "agent"}
    </span>
  );
}

// Human messages ------------------------------------------------------------

export function HumanMessage({ block, ctx }: { block: HumanBlock; ctx: BlockContext }) {
  const [cancelling, setCancelling] = useState(false);
  const queued = block.queuedFor.length > 0 || block.awaitingRoute;
  const cancel = async () => {
    setCancelling(true);
    try {
      await api.cancelDelivery(ctx.channelId, block.event.seq);
    } catch (error) {
      reportError(error);
    } finally {
      setCancelling(false);
    }
  };
  const className = ["fv-msg", "fv-msg--human", queued && "fv-msg--queued", block.cont && !queued && "fv-msg--cont"]
    .filter(Boolean).join(" ");
  const showHead = !block.cont || queued;
  return (
    <article className={className} data-seq={block.event.seq}>
      {showHead ? <PersonAvatar name={ctx.displayName} /> : <span />}
      <div style={{ minWidth: 0 }}>
        {showHead ? (
          <div className="fv-msg-head">
            <span className="fv-msg-author">{ctx.displayName}</span>
            {queued ? (
              <>
                <span className="fv-chip fv-chip--queued">
                  <Clock />
                  {block.awaitingRoute ? "routing…" : `queued → ${block.queuedFor.map((id) => ctx.agents[id]?.handle ?? "agent").join(", ")}`}
                </span>
                {!block.awaitingRoute ? <span className="fv-meta">sends when it's free</span> : null}
              </>
            ) : (
              <span className="fv-meta">{clockTime(block.event.ts)}</span>
            )}
            {block.edited ? <span className="fv-meta">edited</span> : null}
          </div>
        ) : null}
        <div className="fv-msg-body">
          {block.text ? <Markdown text={block.text} handles={ctx.handles} /> : null}
          <Attachments items={block.attachments} />
        </div>
      </div>
      {queued ? (
        <div className="fv-msg-actions">
          <button className="fv-btn fv-btn--ghost fv-btn--sm" onClick={cancel} disabled={cancelling}>
            Cancel
          </button>
        </div>
      ) : null}
    </article>
  );
}

export function Attachments({ items }: { items: AttachmentSummary[] }) {
  if (!items.length) return null;
  return (
    <div className="fv-attachments">
      {items.map((item) => <AttachmentLink key={item.attachment_id} item={item} />)}
    </div>
  );
}

const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

function AttachmentLink({ item }: { item: AttachmentSummary }) {
  const url = api.attachmentUrl(item.attachment_id);
  const image = IMAGE_TYPES.has(item.media_type);
  const thumb = useBlobUrl(image ? api.thumbnailUrl(item.attachment_id) : null);
  const save = () => {
    void downloadAttachment(url, item.filename).catch(reportError);
  };
  if (image && !thumb.failed) {
    return (
      <button type="button" className="fv-attachment fv-attachment--image" onClick={save} title={`Save ${item.filename}`}>
        {thumb.src ? <img src={thumb.src} alt={item.filename} /> : <span className="attachment-placeholder" />}
      </button>
    );
  }
  return (
    <button type="button" className="fv-attachment" onClick={save} title={`Save ${item.filename}`}>
      <FileText size={16} />
      <span className="fv-attachment-name">{item.filename}</span>
      <span className="fv-meta">{bytes(item.size_bytes)}</span>
    </button>
  );
}

// Agent run segments --------------------------------------------------------

export function RunSegment({ block, ctx }: { block: RunBlock; ctx: BlockContext }) {
  const agent = ctx.agents[block.agentId];
  const run = block.runId ? ctx.runs[block.runId] : undefined;
  const partial = useWorkspace((s) => (block.live && block.runId ? s.partials[block.runId]?.text : undefined));
  const [stopping, setStopping] = useState(false);
  const live = block.live;
  const queuedRun = live && block.status === "queued";

  const stop = async () => {
    if (!block.runId) return;
    setStopping(true);
    try {
      await api.cancelRun(block.runId);
    } catch (error) {
      reportError(error);
      setStopping(false);
    }
  };

  const className = ["fv-msg", live && "fv-msg--live", block.cont && "fv-msg--cont"].filter(Boolean).join(" ");
  return (
    <article className={className} data-seq={block.seq}>
      {block.cont ? <span /> : <AgentAvatar agent={agent} status={live ? (queuedRun ? "queued" : "working") : null} />}
      <div style={{ minWidth: 0 }}>
        {!block.cont ? (
          <div className="fv-msg-head">
            <span className="fv-name" style={hueStyle(agent)}>{agent?.handle ?? "agent"}</span>
            {agent ? <span className="fv-cli"><span className="via">via</span><ProviderLogo harness={agent.harness} />{harnessLabel(agent.harness)}</span> : null}
            {live ? (
              <StatusBadge state={queuedRun ? "queued" : "working"} since={queuedRun ? undefined : run?.started_at ?? block.ts}
                label={queuedRun ? "waiting for a run slot" : undefined} />
            ) : (
              <span className="fv-meta">{clockTime(block.ts)}</span>
            )}
          </div>
        ) : null}
        <div className="fv-msg-body">
          {block.messages.map((message) => (
            <Markdown key={message.seq} text={message.payload.text} handles={ctx.handles} />
          ))}
          {live && partial ? (
            <p className="partial-text">{partial}<span className="fv-caret" /></p>
          ) : null}
          {live && !partial && !block.messages.length && !block.tools.length && !queuedRun ? (
            <p className="partial-text fv-meta">Starting…</p>
          ) : null}
        </div>
        {block.tools.length ? <ToolList tools={block.tools} live={live} /> : null}
      </div>
      {live && block.runId && !block.cont ? (
        <div className="fv-msg-actions">
          <button className="fv-btn fv-btn--danger fv-btn--sm" onClick={stop} disabled={stopping}>
            <Square /> Stop
          </button>
        </div>
      ) : null}
    </article>
  );
}

function ToolList({ tools, live }: { tools: ToolEntry[]; live: boolean }) {
  const [open, setOpen] = useState(false);
  // A live run shows its rows; finished groups of two or more collapse.
  if (live || tools.length === 1) {
    const visible = live ? tools.slice(-3) : tools;
    return (
      <div className="fv-tools">
        {live && tools.length > visible.length ? (
          <div className="fv-tool fv-tool-more">
            <span />
            <span className="fv-tool-summary">{tools.length - visible.length} earlier tools</span>
          </div>
        ) : null}
        {visible.map((entry) => <ToolRow key={entry.call.seq} entry={entry} />)}
      </div>
    );
  }
  const summary = toolGroupSummary(tools);
  return (
    <div className="fv-tools">
      <button className="fv-tool fv-tool--group" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? <ChevronDown /> : <ChevronRight />}
        <span className="fv-tool-name">ran {summary.count} tools</span>
        <span className="fv-tool-summary">{summary.parts.join(" · ")}</span>
        <span className="fv-tool-meta">
          {summary.errors ? (
            <span className="fv-chip fv-chip--failed">{summary.errors} err</span>
          ) : summary.pending ? null : (
            <span className="fv-chip fv-chip--success">pass</span>
          )}
          {summary.durationMs ? duration(summary.durationMs) : null}
        </span>
      </button>
      {open ? tools.map((entry) => <ToolRow key={entry.call.seq} entry={entry} child />) : null}
    </div>
  );
}

function ToolRow({ entry, child }: { entry: ToolEntry; child?: boolean }) {
  const [open, setOpen] = useState(false);
  const call: ToolCallPayload = entry.call.payload;
  const result: ToolResultPayload | undefined = entry.result?.payload;
  const error = result?.is_error;
  const pending = !entry.result;
  const output = result?.output ?? "";
  const firstLine = output.split(/\r?\n/).find((line) => line.trim()) ?? "";
  return (
    <>
      <button className={`fv-tool${child ? " fv-tool--child" : ""}${error ? " fv-tool--error" : ""}`}
        onClick={() => setOpen(!open)} aria-expanded={open} disabled={pending && !call.input}>
        {pending ? <span className="tool-glyph"><WorkingDots /></span> : open ? <ChevronDown /> : <ChevronRight />}
        <span className="fv-tool-name">{toolName(call)}</span>
        <span className="fv-tool-summary">{call.summary ?? ""}</span>
        <span className="fv-tool-meta">
          {pending ? <Elapsed since={entry.call.ts} /> : duration(result?.duration_ms)}
        </span>
      </button>
      {!pending && firstLine && !open ? (
        <div className="fv-tool-result">
          <span className="tool-result-line"><CornerDownLeft size={11} /> {firstLine}</span>
          <span>{result?.lines !== undefined ? `${result.lines} lines · ` : ""}{bytes(result?.bytes)}</span>
        </div>
      ) : null}
      {open ? (
        <pre className="fv-tool-output">
          {output || JSON.stringify(call.input, null, 2)}
          {result?.truncated ? "\n… output truncated" : ""}
        </pre>
      ) : null}
    </>
  );
}

// Notices ----------------------------------------------------------------------

export function RoutingNotice({ event, ctx }: { event: WorkspaceEvent<RoutingPayload>; ctx: BlockContext }) {
  const payload = event.payload;
  const [adding, setAdding] = useState<string | null>(null);
  if (payload.reason_code === "none" || !payload.agents.length) {
    const suggestions = (payload.suggested_agents ?? []).filter((id) => !ctx.memberIds.has(id) && ctx.agents[id] && !ctx.agents[id].retired_at);
    const add = async (agentId: string) => {
      setAdding(agentId);
      try {
        await api.addMember(ctx.channelId, agentId);
      } catch (error) {
        reportError(error);
      } finally {
        setAdding(null);
      }
    };
    return (
      <div className="fv-notice fv-notice--failed">
        <Ban />
        <span className="notice-text">routed → none · {payload.reason}</span>
        {suggestions.map((id) => (
          <button key={id} className="fv-btn fv-btn--sm" onClick={() => add(id)} disabled={adding === id}>
            Add {ctx.agents[id].handle}
          </button>
        ))}
      </div>
    );
  }
  const reason = payload.reason_code === "router_failed_random"
    ? `router failed, picked at random${payload.error ? ` · ${payload.error}` : ""}`
    : `reason: ${payload.reason}`;
  return (
    <div className="fv-notice">
      <ArrowRight />
      <span>routed →</span>
      {payload.agents.map((id) => <AgentChip key={id} agent={ctx.agents[id]} />)}
      <span>{reason}</span>
    </div>
  );
}

export function RunEnd({ event, ctx }: { event: WorkspaceEvent<RunStatusPayload>; ctx: BlockContext }) {
  const payload = event.payload;
  const agent = ctx.agents[payload.agent_id];
  if (payload.status === "failed") {
    return (
      <div className="fv-run fv-run--failed" role="alert">
        <Square fill="currentColor" />
        <AgentChip agent={agent} />
        <span>run failed · {payload.text ?? payload.error?.message ?? "the harness reported an error"}</span>
      </div>
    );
  }
  return (
    <div className="fv-run" title={payload.error?.message}>
      <Square />
      <AgentChip agent={agent} />
      <span>run cancelled{payload.duration_ms !== null && payload.duration_ms !== undefined ? ` after ${duration(payload.duration_ms)}` : ""}</span>
    </div>
  );
}

export function Divider({ event, variant }: { event: WorkspaceEvent; variant: "reset" | "checkpoint" }) {
  if (variant === "reset") {
    return (
      <div className="fv-divider fv-divider--reset" role="separator">
        <span><RotateCcw /> context reset · {dayTime(event.ts)}</span>
      </div>
    );
  }
  const covers = (event.payload as { covers_through_seq?: number }).covers_through_seq;
  return (
    <div className="fv-divider fv-divider--checkpoint" role="separator">
      <span><Bookmark /> checkpoint · earlier context summarized{covers ? ` through #${covers}` : ""}</span>
    </div>
  );
}

export function Notice({ event, ctx }: { event: WorkspaceEvent; ctx: BlockContext }) {
  const payload = event.payload as Record<string, unknown>;
  const handle = (id: unknown, fallback: unknown) => (typeof id === "string" && ctx.agents[id]?.handle) || String(fallback ?? "agent");
  switch (event.kind) {
    case "member_added":
      return <div className="fv-notice"><UserPlus /><span>{handle(payload.agent_id, payload.handle)} joined the channel</span></div>;
    case "member_removed":
      return <div className="fv-notice"><UserMinus /><span>{handle(payload.agent_id, payload.handle)} left the channel</span></div>;
    case "cwd_changed":
      return (
        <div className="fv-notice">
          <Folder />
          <span>working directory changed to <span className="fv-mono">{displayPath(String(payload.cwd))}</span>
            {payload.managed ? " (managed)" : ""} · agents start with a fresh session there</span>
        </div>
      );
    case "channel_changed":
      return (
        <div className="fv-notice">
          <Hash />
          <span>{payload.archived_at ? "channel archived" : `channel is now #${String(payload.name)}`}</span>
        </div>
      );
    case "delivery_cancelled": {
      const ids = (payload.agent_ids as (string | null)[]) ?? [];
      const names = ids.map((id) => (id ? handle(id, "agent") : "routing")).join(", ");
      return (
        <div className="fv-notice">
          <X />
          <span>{payload.retracted ? "you cancelled a queued message" : `you cancelled delivery to ${names}`}</span>
        </div>
      );
    }
    default:
      return <div className="fv-notice"><span>{String(payload.text ?? event.kind)}</span></div>;
  }
}
