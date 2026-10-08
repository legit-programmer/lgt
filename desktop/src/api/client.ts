import type {
  Agent, AgentInput, AgentStatus, Attachment, ChannelSummary, Channel, Command, ContextStats,
  Harness, HarnessLimits, Member, Profile, QueueItem, Run, RunLog, SearchResults, Template,
  UsageRow, WorkspaceEvent,
} from "./types";

const FALLBACK_URL = "http://127.0.0.1:8000";
let baseUrl: string | null = null;

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Resolve the backend URL once: the shell's setting, then a Vite variable. */
export async function resolveBackendUrl(): Promise<string> {
  if (baseUrl) return baseUrl;
  let url = import.meta.env.VITE_LGT_BACKEND_URL as string | undefined;
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    url = await invoke<string>("backend_url");
  }
  baseUrl = (url || FALLBACK_URL).replace(/\/+$/, "");
  return baseUrl;
}

export function backendUrl(): string {
  if (!baseUrl) throw new Error("backend URL is not resolved yet");
  return baseUrl;
}

export function socketUrl(): string {
  return backendUrl().replace(/^http/, "ws") + "/ws";
}

export function assetUrl(path: string): string {
  return backendUrl() + path;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(method: string, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof Blob) {
    payload = body;
    headers["Content-Type"] = body.type || "application/octet-stream";
  } else if (body !== undefined) {
    payload = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }
  let response: Response;
  try {
    response = await fetch(backendUrl() + path, { method, headers, body: payload, ...init });
  } catch {
    throw new ApiError(0, "unreachable", "The Lgt backend is not reachable.");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data?.error;
    const detail = data?.detail;
    const message = error?.message
      ?? (typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : null)
      ?? `Request failed with ${response.status}`;
    throw new ApiError(response.status, error?.code ?? "request_failed", message);
  }
  return data as T;
}

const get = <T>(path: string) => request<T>("GET", path);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
const put = <T>(path: string, body?: unknown) => request<T>("PUT", path, body);
const patch = <T>(path: string, body?: unknown) => request<T>("PATCH", path, body);
const del = <T>(path: string) => request<T>("DELETE", path);

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

const enc = encodeURIComponent;

export const api = {
  health: () => get<{ status: string }>("/health"),

  harnesses: () => get<Harness[]>("/harnesses"),
  scanHarnesses: () => post<Harness[]>("/harnesses/scan"),
  probeCustom: (command: string[], extra_args: string[]) =>
    post<Harness>("/harnesses/custom/probe", { command, extra_args }),
  harnessLimits: (harness: string) => get<HarnessLimits | null>(`/harnesses/${enc(harness)}/limits`),

  templates: () => get<Template[]>("/templates"),
  bootstrap: (agent_templates: string[], cwd: string) =>
    post<{ agents: Agent[]; channel: Channel }>("/bootstrap", { agent_templates, cwd }),
  commands: () => get<Command[]>("/commands"),
  me: () => get<Profile>("/me"),
  updateMe: (display_name: string) => patch<Profile>("/me", { display_name }),

  agents: () => get<Agent[]>("/agents"),
  agentStatuses: () => get<AgentStatus[]>("/agents/status"),
  createAgent: (input: AgentInput) => post<Agent>("/agents", input),
  replaceAgent: (agentId: string, input: AgentInput) => put<Agent>(`/agents/${enc(agentId)}`, input),
  retireAgent: (agentId: string) => post<Agent>(`/agents/${enc(agentId)}/retire`),

  channels: () => get<ChannelSummary[]>("/channels"),
  createChannel: (body: { name: string; kind?: "channel" | "dm"; agent_ids?: string[]; cwd?: string | null }) =>
    post<Channel>("/channels", body),
  renameChannel: (channelId: string, name: string) => patch<Channel>(`/channels/${enc(channelId)}`, { name }),
  archiveChannel: (channelId: string) => post<Channel>(`/channels/${enc(channelId)}/archive`),
  unarchiveChannel: (channelId: string) => post<Channel>(`/channels/${enc(channelId)}/unarchive`),
  markRead: (channelId: string, seq: number) => post<ChannelSummary>(`/channels/${enc(channelId)}/read`, { seq }),
  context: (channelId: string, agentId?: string) =>
    get<ContextStats>(`/channels/${enc(channelId)}/context${query({ agent_id: agentId })}`),
  suggestions: (channelId: string) => get<string[]>(`/channels/${enc(channelId)}/suggestions`),
  members: (channelId: string) => get<Member[]>(`/channels/${enc(channelId)}/members`),
  addMember: (channelId: string, agentId: string) =>
    post<Member[]>(`/channels/${enc(channelId)}/members`, { agent_id: agentId }),
  removeMember: (channelId: string, agentId: string) =>
    del<Member[]>(`/channels/${enc(channelId)}/members/${enc(agentId)}`),
  setCwd: (channelId: string, cwd: string | null) => put<Channel>(`/channels/${enc(channelId)}/cwd`, { cwd }),
  queue: (channelId: string) => get<QueueItem[]>(`/channels/${enc(channelId)}/queue`),
  events: (channelId: string, params: { before_seq?: number; after_seq?: number; limit?: number }) =>
    get<WorkspaceEvent[]>(`/channels/${enc(channelId)}/events${query(params)}`),
  newContext: (channelId: string) => post<WorkspaceEvent>(`/channels/${enc(channelId)}/new`),

  sendMessage: (channelId: string, body: { text: string; mentions?: string[]; attachments?: string[] }) =>
    post<WorkspaceEvent>(`/channels/${enc(channelId)}/messages`, body),
  cancelDelivery: (channelId: string, seq: number, agentIds?: string[]) =>
    post<WorkspaceEvent>(`/channels/${enc(channelId)}/messages/${seq}/cancel`,
      agentIds ? { agent_ids: agentIds } : undefined),

  uploadAttachment: (channelId: string, file: File) =>
    request<Attachment>("POST", `/channels/${enc(channelId)}/attachments${query({ filename: file.name })}`, file),
  deleteAttachment: (attachmentId: string) => del<void>(`/attachments/${enc(attachmentId)}`),
  attachmentUrl: (attachmentId: string) => assetUrl(`/attachments/${enc(attachmentId)}`),
  thumbnailUrl: (attachmentId: string) => assetUrl(`/attachments/${enc(attachmentId)}/thumbnail`),

  channelRuns: (channelId: string) => get<Run[]>(`/channels/${enc(channelId)}/runs`),
  runs: (params: { agent_id?: string; channel_id?: string; status?: "active" | "terminal"; limit?: number }) =>
    get<Run[]>(`/runs${query(params)}`),
  run: (runId: string) => get<Run>(`/runs/${enc(runId)}`),
  runLog: (runId: string, tail = 200) => get<RunLog>(`/runs/${enc(runId)}/log${query({ tail })}`),
  cancelRun: (runId: string) => post<{ status: string }>(`/runs/${enc(runId)}/cancel`),
  usage: (group_by: "agent" | "channel" | "day", since?: string) =>
    get<UsageRow[]>(`/usage${query({ group_by, since })}`),
  search: (q: string, channelId?: string) => get<SearchResults>(`/search${query({ q, channel_id: channelId })}`),
};
