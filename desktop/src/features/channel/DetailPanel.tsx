import { ProviderLogo } from "../../components/ProviderLogo";
import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, ListFilter, Pencil, PlusCircle, RefreshCw, Square, X } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import type { Agent, ChannelSummary, HarnessLimits, LimitWindow, Run } from "../../api/types";
import { AgentAvatar } from "../../components/Avatar";
import { StatusBadge } from "../../components/Status";
import { activeAgents, cliLine, hueStyle } from "../../lib/agents";
import { clockTime, duration, relativeTime, tokens } from "../../lib/format";
import { useUi } from "../../store/ui";
import { reportError, useWorkspace } from "../../store/workspace";

export function DetailPanel({ channel, members }: { channel: ChannelSummary; members: Agent[] }) {
  const tab = useUi((s) => s.detailTab);
  const setTab = useUi((s) => s.setDetailTab);
  const setOpen = useUi((s) => s.setDetailOpen);
  return (
    <aside className="detail" aria-label="Channel details">
      <div className="detail-head">
        <div className="fv-tabs" role="tablist">
          <button role="tab" aria-selected={tab === "agents"} onClick={() => setTab("agents")}>Agents</button>
          <button role="tab" aria-selected={tab === "run"} onClick={() => setTab("run")}>Run</button>
        </div>
        <button className="fv-icon-btn" aria-label="Close panel" onClick={() => setOpen(false)}><X /></button>
      </div>
      {tab === "agents" ? <AgentsTab channel={channel} members={members} /> : <RunTab channel={channel} members={members} />}
    </aside>
  );
}

// Agents tab -------------------------------------------------------------------

function AgentsTab({ channel, members }: { channel: ChannelSummary; members: Agent[] }) {
  return (
    <div className="detail-body">
      <div className="detail-section-head">
        <span className="fv-label">In this channel · {members.length}</span>
        <AddAgentButton channel={channel} members={members} />
      </div>
      {members.map((agent) => <AgentCard key={agent.agent_id} agent={agent} channel={channel} />)}
    </div>
  );
}

function AddAgentButton({ channel, members }: { channel: ChannelSummary; members: Agent[] }) {
  const agents = useWorkspace((s) => s.agents);
  const navigate = useUi((s) => s.navigate);
  const view = useUi((s) => s.view);
  const [open, setOpen] = useState(false);
  const memberIds = new Set(members.map((a) => a.agent_id));
  const candidates = activeAgents(agents).filter((a) => !memberIds.has(a.agent_id));
  const add = async (agent: Agent) => {
    setOpen(false);
    try {
      await api.addMember(channel.channel_id, agent.agent_id);
    } catch (error) {
      reportError(error);
    }
  };
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button className="fv-btn fv-btn--sm"><PlusCircle /> Add agent</button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="fv-menu fv-glass" align="end" sideOffset={6}>
          {candidates.length ? <div className="fv-menu-label fv-label">Add to #{channel.name}</div> : null}
          {candidates.map((agent) => (
            <button key={agent.agent_id} className="fv-menu-item" onClick={() => add(agent)}>
              <AgentAvatar agent={agent} />
              <span className="fv-name" style={hueStyle(agent)}>{agent.handle}</span>
              <span className="fv-meta menu-detail">{agent.description}</span>
            </button>
          ))}
          {candidates.length ? <div className="fv-menu-sep" /> : null}
          <button className="fv-menu-item" onClick={() => { setOpen(false); navigate({ kind: "agent-new", returnTo: view }); }}>
            <Bot /> New agent…
          </button>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function AgentCard({ agent, channel }: { agent: Agent; channel: ChannelSummary }) {
  const status = useWorkspace((s) => s.statuses[agent.agent_id]);
  const harnesses = useQuery({ queryKey: ["harnesses"], queryFn: api.harnesses });
  const navigate = useUi((s) => s.navigate);
  const view = useUi((s) => s.view);
  const showRuns = useUi((s) => s.showRuns);
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const here = channel.active_runs.find((r) => r.agent_id === agent.agent_id);
  const running = status?.active_runs.length ?? 0;
  const state = here ? (here.status === "queued" ? "queued" : "working") : status?.state === "failed" ? "failed" : "idle";

  const remove = async () => {
    setRemoving(true);
    try {
      await api.removeMember(channel.channel_id, agent.agent_id);
      setConfirming(false);
    } catch (error) {
      reportError(error);
    } finally {
      setRemoving(false);
    }
  };

  return (
    <div className="fv-card agent-card">
      <div className="agent-card-top">
        <AgentAvatar agent={agent} status={state} />
        <div className="agent-card-text">
          <span className="fv-name" style={hueStyle(agent)}>{agent.handle}</span>
          <span className="fv-meta fv-mono fv-provider-label"><ProviderLogo harness={agent.harness} />{cliLine(agent, harnesses.data)}</span>
        </div>
        <StatusBadge state={state} since={state === "working" ? here?.started_at : undefined} />
      </div>
      <div className="agent-card-actions">
        <button className="fv-btn fv-btn--sm" onClick={() => showRuns(agent.agent_id)}>
          <ListFilter /> Runs{running ? ` · ${running} running` : ""}
        </button>
        <button className="fv-btn fv-btn--ghost fv-btn--sm" onClick={() => navigate({ kind: "agent-edit", agentId: agent.agent_id, returnTo: view })}>
          <Pencil /> Edit config
        </button>
        <span className="conversation-head-spacer" />
        <button className="fv-icon-btn fv-icon-btn--sm" aria-label={`Remove ${agent.handle} from #${channel.name}`} onClick={() => setConfirming(true)}>
          <X />
        </button>
      </div>
      <Dialog.Root open={confirming} onOpenChange={setConfirming}>
        <Dialog.Portal>
          <Dialog.Overlay className="fv-dialog-overlay" />
          <Dialog.Content className="fv-dialog fv-glass">
            <Dialog.Title className="fv-dialog-title">Remove {agent.handle} from #{channel.name}?</Dialog.Title>
            <Dialog.Description className="fv-dialog-desc">
              Its queued messages here are cancelled{here ? " and its current run stops" : ""}. You can add it back later.
            </Dialog.Description>
            <div className="fv-dialog-actions">
              <Dialog.Close asChild><button className="fv-btn fv-btn--ghost">Keep</button></Dialog.Close>
              <button className="fv-btn fv-btn--danger" onClick={remove} disabled={removing}>Remove</button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

// Run tab -----------------------------------------------------------------------

function RunTab({ channel, members }: { channel: ChannelSummary; members: Agent[] }) {
  const agents = useWorkspace((s) => s.agents);
  const runsInfo = useWorkspace((s) => s.runs);
  const filter = useUi((s) => s.runFilterAgentId);
  const selected = useUi((s) => s.selectedRunId);
  const showRuns = useUi((s) => s.showRuns);
  const selectRun = useUi((s) => s.selectRun);
  // Refetch when any run in this channel changes status.
  const version = Object.values(runsInfo).filter((r) => r.channel_id === channel.channel_id)
    .map((r) => `${r.run_id}:${r.status}`).join("|");
  const runs = useQuery({
    queryKey: ["runs", channel.channel_id, filter, version],
    queryFn: () => api.runs({ channel_id: channel.channel_id, agent_id: filter ?? undefined, limit: 50 }),
    placeholderData: (previous) => previous,
  });

  if (selected) return <RunDetail runId={selected} onBack={() => selectRun(null)} />;

  return (
    <div className="detail-body">
      <div className="detail-section-head">
        <span className="fv-label">Runs in #{channel.name}</span>
      </div>
      <div className="run-filters">
        <button className="fv-chip" aria-pressed={filter === null} data-active={filter === null} onClick={() => showRuns(null)}>All agents</button>
        {members.map((agent) => (
          <button key={agent.agent_id} className="fv-chip" style={filter === agent.agent_id ? hueStyle(agent) : undefined}
            aria-pressed={filter === agent.agent_id} onClick={() => showRuns(agent.agent_id)}>
            {agent.handle}
          </button>
        ))}
      </div>
      {runs.data?.length === 0 ? <p className="fv-meta detail-empty">No runs yet.</p> : null}
      <ul className="run-list">
        {runs.data?.map((run) => <RunRow key={run.run_id} run={run} agent={agents[run.agent_id]} onOpen={() => selectRun(run.run_id)} />)}
      </ul>
    </div>
  );
}

function runState(run: Run): "working" | "queued" | "failed" | "success" | "idle" {
  if (run.status === "running" || run.status === "starting") return "working";
  if (run.status === "queued") return "queued";
  if (run.status === "failed") return "failed";
  if (run.status === "completed") return "success";
  return "idle";
}

function RunRow({ run, agent, onOpen }: { run: Run; agent: Agent | undefined; onOpen: () => void }) {
  const state = runState(run);
  return (
    <li>
      <button className="run-row" onClick={onOpen}>
        <AgentAvatar agent={agent} />
        <span className="run-row-text">
          <span className="run-row-top">
            <span className="fv-name" style={hueStyle(agent)}>{agent?.handle ?? "agent"}</span>
            <span className="fv-meta">{run.started_at ? relativeTime(run.started_at) : "queued"}</span>
          </span>
          <span className="fv-meta fv-mono">
            {tokens(run.tokens_in)} / {tokens(run.tokens_out)} tokens{run.duration_ms ? ` · ${duration(run.duration_ms)}` : ""}
          </span>
        </span>
        <StatusBadge state={state} since={state === "working" ? run.started_at : undefined}
          label={run.status === "cancelled" ? "cancelled" : undefined} />
      </button>
    </li>
  );
}

function RunDetail({ runId, onBack }: { runId: string; onBack: () => void }) {
  const agents = useWorkspace((s) => s.agents);
  const live = useWorkspace((s) => s.runs[runId]?.status);
  const limits = useWorkspace((s) => s.limits);
  const run = useQuery({ queryKey: ["run", runId, live], queryFn: () => api.run(runId) });
  const log = useQuery({ queryKey: ["run-log", runId, live], queryFn: () => api.runLog(runId, 400) });
  const [stopping, setStopping] = useState(false);
  const data = run.data;
  const agent = data ? agents[data.agent_id] : undefined;
  const active = data && ["queued", "starting", "running"].includes(data.status);

  const stop = async () => {
    setStopping(true);
    try {
      await api.cancelRun(runId);
    } catch (error) {
      reportError(error);
    } finally {
      setStopping(false);
    }
  };

  return (
    <div className="detail-body">
      <button className="fv-btn fv-btn--ghost fv-btn--sm run-back" onClick={onBack}><ArrowLeft /> All runs</button>
      {data ? (
        <>
          <div className="run-detail-head">
            <AgentAvatar agent={agent} />
            <span className="fv-name" style={hueStyle(agent)}>{agent?.handle ?? "agent"}</span>
            <StatusBadge state={runState(data)} since={active ? data.started_at : undefined}
              label={data.status === "cancelled" ? "cancelled" : undefined} />
            <span className="conversation-head-spacer" />
            {active ? <button className="fv-btn fv-btn--danger fv-btn--sm" onClick={stop} disabled={stopping}><Square /> Stop</button> : null}
          </div>
          {data.error ? <p className="run-error">{data.error.message}</p> : null}
          <dl className="run-facts">
            <dt>Started</dt><dd>{data.started_at ? clockTime(data.started_at) : "not yet"}</dd>
            <dt>Duration</dt><dd>{data.duration_ms ? duration(data.duration_ms) : active ? "running" : "–"}</dd>
            <dt>Session</dt><dd>{data.session_mode === "resume" ? "resumed" : "cold rebuild"}</dd>
            <dt>Harness</dt><dd className="fv-mono">{data.harness}</dd>
          </dl>
          <div className="fv-label run-subhead">Tokens</div>
          <dl className="run-facts run-facts--tokens">
            <dt>Input</dt><dd>{tokens(data.tokens_in)}</dd>
            <dt>Cached input</dt><dd>{tokens(data.tokens_cached_in)}</dd>
            <dt>Cache writes</dt><dd>{tokens(data.tokens_cache_creation)}</dd>
            <dt>Output</dt><dd>{tokens(data.tokens_out)}</dd>
            <dt>Reasoning</dt><dd>{tokens(data.tokens_reasoning)}</dd>
            <dt>Total</dt><dd>{tokens(data.tokens_total)}</dd>
          </dl>
          <Limits harness={data.harness} limits={limits[data.harness]} />
          <div className="run-log-head">
            <span className="fv-label">Harness log</span>
            <button className="fv-icon-btn fv-icon-btn--sm" aria-label="Reload log" onClick={() => void log.refetch()}><RefreshCw /></button>
          </div>
          <pre className="fv-tool-output run-log">
            {log.data?.lines.length ? log.data.lines.join("\n") : "No stderr output."}
            {log.data?.truncated ? "\n… earlier lines omitted" : ""}
          </pre>
        </>
      ) : (
        <p className="fv-meta detail-empty">{run.isError ? "This run could not be loaded." : "Loading run…"}</p>
      )}
    </div>
  );
}

function windowValue(window: LimitWindow | null | undefined) {
  if (!window) return null;
  const used = window.used_percent ?? window.usedPercent;
  const minutes = window.window_duration_mins ?? window.windowDurationMins;
  const resets = window.resets_at ?? window.resetsAt;
  if (used === undefined) return null;
  const resetAt = typeof resets === "number" ? new Date(resets * 1000) : resets ? new Date(resets) : null;
  return { used, minutes, resetAt };
}

function Limits({ harness, limits }: { harness: string; limits: HarnessLimits | null | undefined }) {
  if (!limits) return null;
  const rows = [
    ["Primary window", windowValue(limits.primary)],
    ["Secondary window", windowValue(limits.secondary)],
  ] as const;
  const visible = rows.filter(([, value]) => value);
  if (!visible.length) return null;
  return (
    <>
      <div className="fv-label run-subhead">{harness} plan usage</div>
      {visible.map(([label, value]) => (
        <div key={label} className="limit-row">
          <div className="limit-row-top">
            <span>{label}{value!.minutes ? ` · ${value!.minutes >= 60 ? `${Math.round(value!.minutes / 60)}h` : `${value!.minutes}m`}` : ""}</span>
            <span className="fv-mono">{value!.used}%</span>
          </div>
          <div className="limit-bar" role="progressbar" aria-valuenow={value!.used} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${Math.min(100, value!.used)}%` }} />
          </div>
          {value!.resetAt ? <span className="fv-meta">resets {clockTime(value!.resetAt.toISOString())}</span> : null}
        </div>
      ))}
    </>
  );
}
