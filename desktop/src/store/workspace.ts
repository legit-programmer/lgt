import { create } from "zustand";
import { api, ApiError } from "../api/client";
import type {
  Agent, AgentStatus, ChannelSummary, ContextStats, HarnessLimits, Profile, QueueItem,
  RunStatus, RunStatusPayload, ServerFrame, UsageRow, WorkspaceEvent,
} from "../api/types";

export type Connection = "connecting" | "open" | "reconnecting" | "unreachable";

export interface Timeline {
  events: Record<number, WorkspaceEvent>;
  /** Lowest loaded seq; older pages load before it. */
  oldestSeq: number | null;
  hasOlder: boolean;
  loading: boolean;
}

export interface RunInfo {
  run_id: string;
  channel_id: string;
  agent_id: string;
  status: RunStatus;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
}

export interface Toast {
  id: number;
  message: string;
}

const TERMINAL: ReadonlySet<RunStatus> = new Set(["completed", "failed", "cancelled"]);
const PAGE = 100;

interface WorkspaceState {
  connection: Connection;
  ready: boolean;
  bootError: string | null;
  lastEventId: number;

  me: Profile | null;
  agents: Record<string, Agent>;
  statuses: Record<string, AgentStatus>;
  channels: Record<string, ChannelSummary>;
  timelines: Record<string, Timeline>;
  partials: Record<string, { channel_id: string; text: string }>;
  runs: Record<string, RunInfo>;
  queues: Record<string, QueueItem[]>;
  contexts: Record<string, ContextStats>;
  usage: UsageRow[];
  limits: Record<string, HarnessLimits | null>;
  toasts: Toast[];

  boot(): Promise<void>;
  applyFrame(frame: ServerFrame): void;
  loadTimeline(channelId: string, force?: boolean): Promise<void>;
  loadOlder(channelId: string): Promise<void>;
  loadAround(channelId: string, seq: number): Promise<void>;
  refreshSummaries(): Promise<void>;
  upsertAgent(agent: Agent): void;
  setConnection(connection: Connection): void;
  toast(message: string): void;
  dismissToast(id: number): void;
}

export const contextKey = (channelId: string, agentId: string) => `${channelId}:${agentId}`;

function emptyTimeline(): Timeline {
  return { events: {}, oldestSeq: null, hasOlder: true, loading: false };
}

function mergeEvents(timeline: Timeline, events: WorkspaceEvent[], older: boolean): Timeline {
  const merged = { ...timeline.events };
  for (const event of events) merged[event.seq] = event;
  const seqs = events.map((e) => e.seq);
  const lowest = seqs.length ? Math.min(...seqs) : null;
  const oldestSeq = lowest === null ? timeline.oldestSeq
    : timeline.oldestSeq === null ? lowest : Math.min(timeline.oldestSeq, lowest);
  return {
    ...timeline,
    events: merged,
    oldestSeq,
    hasOlder: older ? events.length >= PAGE : timeline.hasOlder,
  };
}

function runFromEvent(event: WorkspaceEvent): RunInfo | null {
  if (event.kind !== "run_status" || !event.run_id) return null;
  const payload = event.payload as unknown as RunStatusPayload;
  return {
    run_id: event.run_id,
    channel_id: event.channel_id,
    agent_id: payload.agent_id,
    status: payload.status,
    started_at: payload.started_at ?? null,
    ended_at: payload.ended_at ?? null,
    duration_ms: payload.duration_ms ?? null,
  };
}

let toastId = 0;

export const useWorkspace = create<WorkspaceState>((set, get) => ({
  connection: "connecting",
  ready: false,
  bootError: null,
  lastEventId: 0,
  me: null,
  agents: {},
  statuses: {},
  channels: {},
  timelines: {},
  partials: {},
  runs: {},
  queues: {},
  contexts: {},
  usage: [],
  limits: {},
  toasts: [],

  async boot() {
    try {
      const [agents, channels, statuses, me] = await Promise.all([
        api.agents(), api.channels(), api.agentStatuses(), api.me(),
      ]);
      set({
        agents: Object.fromEntries(agents.map((a) => [a.agent_id, a])),
        channels: Object.fromEntries(channels.map((c) => [c.channel_id, c])),
        statuses: Object.fromEntries(statuses.map((s) => [s.agent_id, s])),
        me,
        ready: true,
        bootError: null,
      });
    } catch (error) {
      set({ bootError: error instanceof ApiError ? error.message : String(error) });
      throw error;
    }
  },

  applyFrame(frame) {
    switch (frame.type) {
      case "event": {
        const event = frame.event;
        set((state) => {
          const next: Partial<WorkspaceState> = { lastEventId: Math.max(state.lastEventId, event.id) };
          const timeline = state.timelines[event.channel_id];
          if (timeline) {
            next.timelines = { ...state.timelines, [event.channel_id]: mergeEvents(timeline, [event], false) };
          }
          const run = runFromEvent(event);
          if (run) {
            next.runs = { ...state.runs, [run.run_id]: { ...state.runs[run.run_id], ...run } };
            if (TERMINAL.has(run.status) && state.partials[run.run_id]) {
              const partials = { ...state.partials };
              delete partials[run.run_id];
              next.partials = partials;
            }
          }
          // The backend clears a run's partial text when it commits a message.
          if (event.kind === "message" && event.run_id && state.partials[event.run_id]) {
            const partials = { ...(next.partials ?? state.partials) };
            delete partials[event.run_id];
            next.partials = partials;
          }
          return next;
        });
        return;
      }
      case "delta":
        set((state) => ({
          partials: {
            ...state.partials,
            [frame.run_id]: {
              channel_id: frame.channel_id,
              text: (state.partials[frame.run_id]?.text ?? "") + frame.text,
            },
          },
        }));
        return;
      case "partial_snapshot":
        set((state) => ({
          partials: { ...state.partials, [frame.run_id]: { channel_id: frame.channel_id, text: frame.text } },
        }));
        return;
      case "queue":
        set((state) => ({ queues: { ...state.queues, [frame.channel_id]: frame.items } }));
        return;
      case "channel_summary": {
        const { type: _type, ...summary } = frame;
        set((state) => ({ channels: { ...state.channels, [summary.channel_id]: summary } }));
        return;
      }
      case "agent_status": {
        const { type: _type, ...status } = frame;
        set((state) => {
          const runs = { ...state.runs };
          for (const active of status.active_runs) {
            const known = runs[active.run_id];
            runs[active.run_id] = {
              run_id: active.run_id,
              channel_id: active.channel_id,
              agent_id: status.agent_id,
              status: known?.status ?? "running",
              started_at: active.started_at ?? known?.started_at ?? null,
              ended_at: null,
              duration_ms: null,
            };
          }
          return { statuses: { ...state.statuses, [status.agent_id]: status }, runs };
        });
        return;
      }
      case "context": {
        const { type: _type, ...stats } = frame;
        set((state) => ({ contexts: { ...state.contexts, [contextKey(stats.channel_id, stats.agent_id)]: stats } }));
        return;
      }
      case "usage":
        if (frame.totals && frame.group_by === "agent") set({ usage: frame.totals });
        return;
      case "harness_limits":
        set((state) => ({ limits: { ...state.limits, [frame.harness]: frame.limits } }));
        return;
      case "me": {
        const { type: _type, ...profile } = frame;
        set({ me: profile });
        return;
      }
      case "agent": {
        const { type: _type, ...agent } = frame;
        get().upsertAgent(agent);
        return;
      }
      case "resync":
        void get().refreshSummaries();
        for (const channelId of frame.channels) {
          if (get().timelines[channelId]) void get().loadTimeline(channelId, true);
        }
        return;
      case "error":
        get().toast(frame.error.message);
        return;
    }
  },

  async loadTimeline(channelId, force = false) {
    const existing = get().timelines[channelId];
    if (existing && !force) return;
    set((state) => ({
      timelines: { ...state.timelines, [channelId]: { ...(force ? emptyTimeline() : existing ?? emptyTimeline()), loading: true } },
    }));
    try {
      const events = await api.events(channelId, { limit: PAGE });
      set((state) => {
        const timeline = mergeEvents(state.timelines[channelId] ?? emptyTimeline(), events, true);
        const runs = { ...state.runs };
        for (const event of events) {
          const run = runFromEvent(event);
          if (run) runs[run.run_id] = { ...runs[run.run_id], ...run };
        }
        return { timelines: { ...state.timelines, [channelId]: { ...timeline, loading: false } }, runs };
      });
    } catch (error) {
      set((state) => ({
        timelines: { ...state.timelines, [channelId]: { ...(state.timelines[channelId] ?? emptyTimeline()), loading: false } },
      }));
      get().toast(error instanceof Error ? error.message : String(error));
    }
  },

  async loadOlder(channelId) {
    const timeline = get().timelines[channelId];
    if (!timeline || timeline.loading || !timeline.hasOlder || timeline.oldestSeq === null) return;
    if (timeline.oldestSeq <= 1) {
      set((state) => ({ timelines: { ...state.timelines, [channelId]: { ...timeline, hasOlder: false } } }));
      return;
    }
    set((state) => ({ timelines: { ...state.timelines, [channelId]: { ...timeline, loading: true } } }));
    try {
      const events = await api.events(channelId, { before_seq: timeline.oldestSeq, limit: PAGE });
      set((state) => {
        const current = state.timelines[channelId] ?? emptyTimeline();
        const merged = mergeEvents(current, events, true);
        const runs = { ...state.runs };
        for (const event of events) {
          const run = runFromEvent(event);
          if (run) runs[run.run_id] = { ...run, ...runs[run.run_id] };
        }
        return { timelines: { ...state.timelines, [channelId]: { ...merged, loading: false } }, runs };
      });
    } catch (error) {
      set((state) => ({ timelines: { ...state.timelines, [channelId]: { ...timeline, loading: false } } }));
      get().toast(error instanceof Error ? error.message : String(error));
    }
  },

  async loadAround(channelId, seq) {
    await get().loadTimeline(channelId);
    // Page back until the anchor is loaded.
    for (let guard = 0; guard < 50; guard++) {
      const timeline = get().timelines[channelId];
      if (!timeline || timeline.oldestSeq === null || timeline.oldestSeq <= seq || !timeline.hasOlder) return;
      await get().loadOlder(channelId);
    }
  },

  async refreshSummaries() {
    try {
      const [channels, statuses] = await Promise.all([api.channels(), api.agentStatuses()]);
      set({
        channels: Object.fromEntries(channels.map((c) => [c.channel_id, c])),
        statuses: Object.fromEntries(statuses.map((s) => [s.agent_id, s])),
      });
    } catch (error) {
      get().toast(error instanceof Error ? error.message : String(error));
    }
  },

  upsertAgent(agent) {
    set((state) => ({ agents: { ...state.agents, [agent.agent_id]: agent } }));
  },

  setConnection(connection) {
    set({ connection });
  },

  toast(message) {
    const id = ++toastId;
    set((state) => ({ toasts: [...state.toasts.slice(-3), { id, message }] }));
    window.setTimeout(() => get().dismissToast(id), 6000);
  },

  dismissToast(id) {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },
}));

/** Report a failed action as a toast and rethrow nothing. */
export function reportError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  useWorkspace.getState().toast(message);
}
