// Types for the Lgt backend API (docs/backend-reference.md).

export type HarnessId = "codex" | "claude" | "gemini" | "custom" | (string & {});

export interface Avatar {
  style: string;
  seed: string;
}

export interface Agent {
  agent_id: string;
  handle: string;
  name: string;
  description: string;
  harness: HarnessId;
  model: string;
  system_prompt: string;
  allowed_tools: string[];
  default_cwd: string | null;
  permission_mode: string;
  created_at: string;
  updated_at: string;
  avatar: Avatar;
  hue: number;
  extra_args: string[];
  command: string[];
  retired_at: string | null;
  dm_channel_id: string | null;
}

export interface AgentInput {
  handle: string;
  name: string;
  description: string;
  harness: HarnessId;
  model: string;
  system_prompt: string;
  allowed_tools: string[];
  default_cwd: string | null;
  avatar: Avatar | null;
  extra_args: string[];
  command: string[];
}

export interface HarnessCapabilities {
  resume: boolean;
  interrupt: boolean;
  text_delta: boolean;
  allowed_tools: boolean;
  image_input: boolean;
  usage: boolean;
  rate_limits: boolean;
}

export interface HarnessModel {
  id: string;
  label: string;
  description: string;
  default: boolean;
}

export interface HarnessTool {
  id: string;
  label: string;
  description: string;
}

export interface Harness {
  harness: HarnessId;
  found: boolean;
  path: string | null;
  version: string | null;
  auth: "signed_in" | "signed_out" | "unknown";
  capabilities: HarnessCapabilities;
  models: HarnessModel[];
  tools: HarnessTool[];
}

export interface Template {
  id: string;
  name: string;
  description: string;
  harness: HarnessId;
  model: string;
  system_prompt: string;
  allowed_tools: string[];
}

export interface Member {
  member_kind: "human" | "agent";
  member_id: string;
  joined_at: string;
}

export interface Preview {
  seq: number;
  kind: string;
  author_id: string;
  text_excerpt: string;
}

export interface ActiveRunRef {
  run_id: string;
  agent_id: string;
  status: RunStatus;
  started_at: string | null;
}

export interface Channel {
  channel_id: string;
  kind: "channel" | "dm";
  name: string;
  cwd: string;
  cwd_managed: boolean;
  next_seq: number;
  created_at: string;
  archived_at: string | null;
}

export interface ChannelSummary extends Channel {
  members: Member[];
  last_activity_at: string;
  preview: Preview | null;
  unread_count: number;
  active_runs: ActiveRunRef[];
}

export type RunStatus = "queued" | "starting" | "running" | "completed" | "failed" | "cancelled";

export interface RunError {
  code: string;
  message: string;
  exit_code: number | null;
  signal: string | null;
}

export interface TokenCounters {
  tokens_in: number;
  tokens_out: number;
  tokens_cached_in: number;
  tokens_cache_creation: number;
  tokens_reasoning: number;
  tokens_total: number;
}

export interface Run extends TokenCounters {
  run_id: string;
  channel_id: string;
  agent_id: string;
  trigger_seq: number;
  session_mode: "resume" | "cold";
  harness: HarnessId;
  cwd: string;
  status: RunStatus;
  error: RunError | null;
  exit_code: number | null;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
}

export interface RunLog {
  run_id: string;
  lines: string[];
  truncated: boolean;
}

export interface Activity {
  kind: "tool" | "writing";
  summary: string;
  since: string;
}

export interface AgentStatus {
  agent_id: string;
  state: "idle" | "working" | "queued" | "failed";
  active_runs: { run_id: string; channel_id: string; started_at: string | null }[];
  activity: Activity | null;
  last_failure: { run_id: string; error: RunError | null; at: string | null } | null;
}

export interface ContextStats {
  channel_id: string;
  agent_id: string;
  mode: "resume" | "cold";
  start_seq: number;
  messages_in_context: number;
  context_tokens: number | null;
  model_context_window: number | null;
  checkpoint_seq: number | null;
}

export interface UsageRow extends TokenCounters {
  agent?: string;
  channel?: string;
  day?: string;
  run_count: number;
}

export interface LimitWindow {
  used_percent?: number;
  usedPercent?: number;
  window_duration_mins?: number | null;
  windowDurationMins?: number | null;
  resets_at?: number | string | null;
  resetsAt?: number | string | null;
}

export interface HarnessLimits {
  primary?: LimitWindow | null;
  secondary?: LimitWindow | null;
  plan_type?: string | null;
  planType?: string | null;
  [key: string]: unknown;
}

export interface Profile {
  human_id: string;
  display_name: string;
}

export interface Command {
  name: string;
  description: string;
  usage: string;
}

export interface QueueItem {
  queue_id: number;
  event_seq: number;
  agent_id: string | null;
  state: "awaiting_route" | "awaiting_agent";
  created_at: string;
}

export interface AttachmentSummary {
  attachment_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
}

export interface Attachment extends AttachmentSummary {
  channel_id: string;
  sha256: string;
  message_seq: number | null;
  created_at: string;
  url: string;
}

export interface SearchResults {
  channels: { channel_id: string; name: string }[];
  agents: { agent_id: string; handle: string; name: string }[];
  messages: { channel_id: string; seq: number; kind: string; author_id: string; text: string }[];
}

// Events ---------------------------------------------------------------

export interface WorkspaceEvent<P = Record<string, unknown>> {
  id: number;
  channel_id: string;
  seq: number;
  ts: string;
  kind: string;
  author_kind: "human" | "agent" | "system";
  author_id: string;
  run_id: string | null;
  chain_id: number;
  hop: number;
  payload: P;
}

export interface MessagePayload {
  text: string;
  mentions: string[];
  author_handle?: string;
  attachments?: AttachmentSummary[];
}

export interface ToolCallPayload {
  tool_call_id: string;
  tool?: string;
  label?: string;
  summary?: string;
  name?: string;
  input?: unknown;
  author_handle?: string;
}

export interface ToolResultPayload {
  tool_call_id: string;
  is_error: boolean;
  exit_code?: number | null;
  duration_ms?: number | null;
  bytes?: number;
  lines?: number;
  truncated?: boolean;
  output?: string;
}

export interface RunStatusPayload {
  run_id: string;
  agent_id: string;
  status: RunStatus;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  error?: RunError;
  text?: string;
}

export interface RoutingPayload {
  for_seqs: number[];
  agents: string[];
  suggested_agents: string[];
  method: "mention" | "router";
  reason_code: "mention" | "router" | "router_failed_random" | "none";
  reason: string;
  error?: string;
}

// WebSocket frames --------------------------------------------------------

export type ServerFrame =
  | { type: "event"; event: WorkspaceEvent }
  | { type: "delta"; run_id: string; channel_id: string; text: string }
  | { type: "partial_snapshot"; run_id: string; channel_id: string; text: string }
  | { type: "queue"; channel_id: string; items: QueueItem[] }
  | ({ type: "channel_summary" } & ChannelSummary)
  | ({ type: "agent_status" } & AgentStatus)
  | ({ type: "context" } & ContextStats)
  | ({ type: "usage"; group_by?: string; totals?: UsageRow[]; run_id?: string; agent_id?: string;
      channel_id?: string; harness?: string } & Partial<TokenCounters>)
  | { type: "harness_limits"; harness: string; limits: HarnessLimits | null }
  | ({ type: "me" } & Profile)
  | ({ type: "agent" } & Agent)
  | { type: "resync"; channels: string[] }
  | { type: "error"; error: { code: string; message: string } };

export type ClientCommand =
  | { type: "send_message"; channel_id: string; text: string; mentions?: string[]; attachments?: string[] }
  | { type: "edit_message"; channel_id: string; target_seq: number; text?: string; deleted?: boolean }
  | { type: "cancel_run"; run_id: string }
  | { type: "new_context"; channel_id: string }
  | { type: "cancel_delivery"; channel_id: string; target_seq: number; agent_ids?: string[] };
