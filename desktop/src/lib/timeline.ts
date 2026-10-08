import type {
  AttachmentSummary, MessagePayload, QueueItem, RoutingPayload, RunStatus, RunStatusPayload,
  ToolCallPayload, ToolResultPayload, WorkspaceEvent,
} from "../api/types";

/**
 * Turns a channel's event log into the timeline blocks of the design:
 * human messages, agent run segments with their tool groups, routing
 * notices, run failures, and dividers. Pure, so it is unit tested.
 */

export interface ToolEntry {
  call: WorkspaceEvent<ToolCallPayload>;
  result: WorkspaceEvent<ToolResultPayload> | null;
}

export interface HumanBlock {
  type: "human";
  key: string;
  event: WorkspaceEvent<MessagePayload>;
  text: string;
  edited: boolean;
  deleted: boolean;
  attachments: AttachmentSummary[];
  queuedFor: string[];
  awaitingRoute: boolean;
  cont: boolean;
}

export interface RunBlock {
  type: "run";
  key: string;
  runId: string | null;
  agentId: string;
  seq: number;
  ts: string;
  messages: WorkspaceEvent<MessagePayload>[];
  tools: ToolEntry[];
  /** True on the run's last segment while the run is active. */
  live: boolean;
  status: RunStatus | null;
  cont: boolean;
}

export interface RoutingBlock {
  type: "routing";
  key: string;
  event: WorkspaceEvent<RoutingPayload>;
}

export interface RunEndBlock {
  type: "run_end";
  key: string;
  event: WorkspaceEvent<RunStatusPayload>;
}

export interface DividerBlock {
  type: "divider";
  key: string;
  variant: "reset" | "checkpoint";
  event: WorkspaceEvent;
}

export interface NoticeBlock {
  type: "notice";
  key: string;
  event: WorkspaceEvent;
}

export type Block = HumanBlock | RunBlock | RoutingBlock | RunEndBlock | DividerBlock | NoticeBlock;

export interface RunState {
  status: RunStatus;
  agent_id: string;
}

const ACTIVE: ReadonlySet<RunStatus> = new Set(["queued", "starting", "running"]);
const NOTICE_KINDS = new Set([
  "member_added", "member_removed", "cwd_changed", "channel_changed", "delivery_cancelled", "system",
]);

function as<P>(event: WorkspaceEvent): WorkspaceEvent<P> {
  return event as unknown as WorkspaceEvent<P>;
}

export function sortedEvents(events: Record<number, WorkspaceEvent>): WorkspaceEvent[] {
  return Object.values(events).sort((a, b) => a.seq - b.seq);
}

export function buildTimeline(
  events: WorkspaceEvent[],
  runs: Record<string, RunState | undefined>,
  queue: QueueItem[] = [],
): Block[] {
  const edits = new Map<number, { text?: string; deleted?: boolean }>();
  for (const event of events) {
    if (event.kind !== "message_edit") continue;
    const payload = event.payload as { target_seq: number; text?: string; deleted?: boolean };
    edits.set(payload.target_seq, { ...edits.get(payload.target_seq), ...payload });
  }

  const queuedFor = new Map<number, string[]>();
  const awaitingRoute = new Set<number>();
  for (const item of queue) {
    if (item.state === "awaiting_route") awaitingRoute.add(item.event_seq);
    else if (item.agent_id) queuedFor.set(item.event_seq, [...(queuedFor.get(item.event_seq) ?? []), item.agent_id]);
  }

  const blocks: Block[] = [];
  const open = new Map<string, RunBlock>();
  const toolsById = new Map<string, ToolEntry>();
  const lastSegment = new Map<string, RunBlock>();

  const closeSegments = () => open.clear();

  const segmentFor = (event: WorkspaceEvent, agentId: string): RunBlock => {
    const key = event.run_id ?? `solo:${event.seq}`;
    let block = open.get(key);
    if (!block) {
      block = {
        type: "run",
        key: `run:${key}:${event.seq}`,
        runId: event.run_id,
        agentId,
        seq: event.seq,
        ts: event.ts,
        messages: [],
        tools: [],
        live: false,
        status: null,
        cont: false,
      };
      open.set(key, block);
      blocks.push(block);
    }
    if (event.run_id) lastSegment.set(event.run_id, block);
    return block;
  };

  for (const event of events) {
    switch (event.kind) {
      case "message": {
        if (event.author_kind === "human") {
          closeSegments();
          const payload = event.payload as unknown as MessagePayload;
          const edit = edits.get(event.seq);
          blocks.push({
            type: "human",
            key: `msg:${event.seq}`,
            event: as<MessagePayload>(event),
            text: edit?.text ?? payload.text,
            edited: edit?.text !== undefined,
            deleted: edit?.deleted === true,
            attachments: payload.attachments ?? [],
            queuedFor: queuedFor.get(event.seq) ?? [],
            awaitingRoute: awaitingRoute.has(event.seq),
            cont: false,
          });
        } else {
          segmentFor(event, event.author_id).messages.push(as<MessagePayload>(event));
        }
        break;
      }
      case "tool_call": {
        const entry: ToolEntry = { call: as<ToolCallPayload>(event), result: null };
        const id = (event.payload as unknown as ToolCallPayload).tool_call_id;
        if (id) toolsById.set(`${event.run_id}:${id}`, entry);
        segmentFor(event, event.author_id).tools.push(entry);
        break;
      }
      case "tool_result": {
        const id = (event.payload as unknown as ToolResultPayload).tool_call_id;
        const entry = toolsById.get(`${event.run_id}:${id}`);
        if (entry) entry.result = as<ToolResultPayload>(event);
        else segmentFor(event, event.author_id).tools.push({ call: syntheticCall(event), result: as<ToolResultPayload>(event) });
        break;
      }
      case "run_status": {
        const payload = event.payload as unknown as RunStatusPayload;
        if (payload.status === "failed" || payload.status === "cancelled") {
          blocks.push({ type: "run_end", key: `end:${event.seq}`, event: as<RunStatusPayload>(event) });
        } else if (event.run_id && !lastSegment.has(event.run_id) && ACTIVE.has(payload.status)) {
          // A run with no output yet still shows its working header here.
          segmentFor(event, payload.agent_id);
        }
        break;
      }
      case "routing_decision":
        blocks.push({ type: "routing", key: `route:${event.seq}`, event: as<RoutingPayload>(event) });
        break;
      case "context_reset":
        closeSegments();
        blocks.push({ type: "divider", key: `div:${event.seq}`, variant: "reset", event });
        break;
      case "context_checkpoint":
        blocks.push({ type: "divider", key: `div:${event.seq}`, variant: "checkpoint", event });
        break;
      default:
        if (NOTICE_KINDS.has(event.kind)) blocks.push({ type: "notice", key: `note:${event.seq}`, event });
    }
  }

  // Mark the live segment of each active run, then drop empty finished ones.
  for (const [runId, block] of lastSegment) {
    const run = runs[runId];
    block.status = run?.status ?? null;
    block.live = run ? ACTIVE.has(run.status) : false;
  }
  const visible = blocks.filter((block) =>
    block.type !== "run" || block.live || block.messages.length > 0 || block.tools.length > 0);

  // Consecutive blocks from the same speaker drop the header.
  for (let index = 1; index < visible.length; index++) {
    const previous = visible[index - 1];
    const block = visible[index];
    if (block.type === "human" && previous.type === "human" && !previous.deleted) block.cont = true;
    if (block.type === "run" && previous.type === "run" && previous.agentId === block.agentId
        && previous.runId === block.runId) block.cont = true;
  }
  return visible;
}

function syntheticCall(event: WorkspaceEvent): WorkspaceEvent<ToolCallPayload> {
  const payload = event.payload as unknown as ToolResultPayload;
  return { ...event, kind: "tool_call", payload: { tool_call_id: payload.tool_call_id, tool: "tool", label: "Tool" } };
}

/** Display name for a tool row: Bash, Read, Edit. */
export function toolName(call: ToolCallPayload): string {
  const raw = call.label || call.tool || call.name || "tool";
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

/** Group summary: "ran 3 tools", "read · edit · bash", errors and total duration. */
export function toolGroupSummary(tools: ToolEntry[]) {
  const names: string[] = [];
  const counts = new Map<string, number>();
  for (const entry of tools) {
    const name = (entry.call.payload.tool || entry.call.payload.label || entry.call.payload.name || "tool").toLowerCase();
    if (!counts.has(name)) names.push(name);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const errors = tools.filter((entry) => entry.result?.payload.is_error).length;
  const pending = tools.filter((entry) => !entry.result).length;
  const durationMs = tools.reduce((sum, entry) => sum + (entry.result?.payload.duration_ms ?? 0), 0);
  return {
    count: tools.length,
    parts: names.map((name) => (counts.get(name)! > 1 ? `${name} ×${counts.get(name)}` : name)),
    errors,
    pending,
    durationMs,
  };
}
