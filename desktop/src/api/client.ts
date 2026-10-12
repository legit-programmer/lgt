import type {
  Agent, AgentInput, AgentStatus, Attachment, ChannelSummary, Channel, Command, ContextStats,
  ConnectionInfo, Device, DevicePairing, Harness, HarnessModel, HarnessLimits, Member, Profile, QueueItem, Run, RunLog, SearchResults, Template,
  UsageRow, WorkspaceEvent, ReplyQuote, ReplyRequest,
} from "./types";
import { isMobile } from "../lib/platform";

const FALLBACK_URL = "http://127.0.0.1:8000";
let baseUrl: string | null = null;
let launchToken: string | null = null;
let resolving: Promise<string> | null = null;
const PAIRED_CONNECTION_KEY = "lgt.pairedConnection";
let pairedConnection = false;

export function parsePairing(raw: string): DevicePairing {
  const data = JSON.parse(raw) as DevicePairing;
  if (!data || data.type !== "lgt-device" || data.version !== 1
      || typeof data.url !== "string" || typeof data.device_id !== "string" || !data.device_id
      || typeof data.name !== "string" || !data.name.trim()
      || typeof data.token !== "string" || !/^lgt_device_[A-Za-z0-9_-]{43}$/.test(data.token)
      || /[\s\\]/.test(data.url)) throw new Error("Invalid Lgt pairing code.");
  const url = new URL(data.url);
  if (!["http:", "https:"].includes(url.protocol) || !url.hostname
      || ["0.0.0.0", "[::]"].includes(url.hostname) || url.port === "0"
      || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("The pairing address must be an HTTP(S) origin.");
  }
  return { type: "lgt-device", version: 1, url: url.origin,
    device_id: data.device_id, name: data.name, token: data.token };
}

function storedPairing(): DevicePairing | null {
  try {
    const raw = localStorage.getItem(PAIRED_CONNECTION_KEY);
    return raw ? parsePairing(raw) : null;
  } catch { return null; }
}

/** Verify a scanned/pasted QR payload before persisting its device credential. */
export async function savePairedConnection(raw: string): Promise<void> {
  const pairing = parsePairing(raw);
  const response = await fetch(pairing.url + "/connection", {
    headers: { Authorization: `Bearer ${pairing.token}` }, redirect: "error",
  });
  if (!response.ok) throw new Error("The device credential was rejected by the workspace.");
  const info = await response.json() as ConnectionInfo;
  if (info.device_id !== pairing.device_id || info.local_admin !== false) {
    throw new Error("The workspace did not recognize this paired device.");
  }
  localStorage.setItem(PAIRED_CONNECTION_KEY, JSON.stringify(pairing));
}

export function forgetPairedConnection(): void {
  localStorage.removeItem(PAIRED_CONNECTION_KEY);
}

export function isRemoteConnection(): boolean {
  if (pairedConnection) return true;
  if (!baseUrl) return false;
  return !["127.0.0.1", "localhost", "[::1]"].includes(new URL(baseUrl).hostname);
}

/** A mobile client has no local workspace and must be paired before it can boot. */
export class PairingRequiredError extends Error {
  constructor() {
    super("Pair this device with a workspace to continue.");
    this.name = "PairingRequiredError";
  }
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Discover/start the daemon; concurrent boots share one launch attempt. */
export function resolveBackendUrl(): Promise<string> {
  if (resolving) return resolving;
  resolving = (async () => {
    let url = import.meta.env.VITE_LGT_BACKEND_URL as string | undefined;
    let token: string | null = null;
    const pairing = storedPairing();
    pairedConnection = pairing !== null;
    if (pairing) {
      url = pairing.url;
      token = pairing.token;
    } else if (isMobile) {
      throw new PairingRequiredError();
    } else if (isTauri()) {
      const { invoke } = await import("@tauri-apps/api/core");
      const connection = await invoke<{ url: string; token: string | null; managed: boolean }>("ensure_backend");
      url = connection.url;
      token = connection.token;
    }
    baseUrl = (url || FALLBACK_URL).replace(/\/+$/, "");
    launchToken = token;
    return baseUrl;
  })().finally(() => { resolving = null; });
  return resolving;
}

export async function quitWorkspace(): Promise<void> {
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke(isRemoteConnection() ? "quit_client" : "quit_workspace");
}

/** Send credentials only to the selected backend, with redirects disabled. */
export function fetchBackendResource(url: string, init?: RequestInit): Promise<Response> {
  if (new URL(url).origin !== new URL(backendUrl()).origin) {
    return Promise.reject(new Error("The resource is outside this Lgt backend."));
  }
  const headers = new Headers(init?.headers);
  if (launchToken) headers.set("Authorization", `Bearer ${launchToken}`);
  return fetch(url, { ...init, headers, redirect: "error" });
}

export function socketHandshake(lastId: number): { last_id: number; token?: string } {
  return launchToken ? { last_id: lastId, token: launchToken } : { last_id: lastId };
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
    response = await fetchBackendResource(backendUrl() + path, { method, headers, body: payload, ...init });
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
  health: () => get<{ status: string; application: string; api_version: number; pid: number }>("/health"),
  connectionInfo: () => get<ConnectionInfo>("/connection"),
  devices: () => get<Device[]>("/devices"),
  pairDevice: (name: string) => post<{ device: Device; pairing: DevicePairing }>("/devices", { name }),
  renameDevice: (deviceId: string, name: string) => patch<Device>(`/devices/${enc(deviceId)}`, { name }),
  revokeDevice: (deviceId: string) => post<Device>(`/devices/${enc(deviceId)}/revoke`),

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
  agentModels: (agentId: string) => get<HarnessModel[]>(`/agents/${enc(agentId)}/models`),
  updateAgentInference: (agentId: string, input: { model?: string; reasoning_effort?: string | null }) =>
    patch<Agent>(`/agents/${enc(agentId)}/inference`, input),
  agentStatuses: () => get<AgentStatus[]>("/agents/status"),
  createAgent: (input: AgentInput) => post<Agent>("/agents", input),
  replaceAgent: (agentId: string, input: AgentInput) => put<Agent>(`/agents/${enc(agentId)}`, input),
  retireAgent: (agentId: string) => post<Agent>(`/agents/${enc(agentId)}/retire`),

  channels: () => get<ChannelSummary[]>("/channels"),
  createChannel: (body: { name: string; kind?: "channel" | "dm"; agent_ids?: string[]; cwd?: string | null }) =>
    post<Channel>("/channels", body),
  renameChannel: (channelId: string, name: string) => patch<Channel>(`/channels/${enc(channelId)}`, { name }),
  setHandoff: (channelId: string, allow_handoff: boolean) =>
    patch<Channel>(`/channels/${enc(channelId)}`, { allow_handoff }),
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

  sendMessage: (channelId: string, body: { text: string; mentions?: string[]; attachments?: string[]; reply_to_seq?: number; reply_selection?: string }) =>
    post<WorkspaceEvent>(`/channels/${enc(channelId)}/messages`, body),
  previewReply: (channelId: string, body: ReplyRequest) =>
    post<ReplyQuote>(`/channels/${enc(channelId)}/reply-preview`, body),
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
