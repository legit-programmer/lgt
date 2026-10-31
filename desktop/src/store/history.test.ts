import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { WorkspaceEvent } from "../api/types";
import { useWorkspace } from "./workspace";

vi.mock("../api/client", async (original) => ({
  ...await original<typeof import("../api/client")>(),
  api: { events: vi.fn(), channels: vi.fn().mockResolvedValue([]), agentStatuses: vi.fn().mockResolvedValue([]) },
}));
const base = useWorkspace.getState();
const events = (start: number, count: number): WorkspaceEvent[] => Array.from({ length: count }, (_, i) => ({
  id: start + i, seq: start + i, channel_id: "c1", kind: "message", ts: "now",
  author_kind: "human", author_id: "local", run_id: null, chain_id: 1, hop: 0,
  payload: { text: `Message ${start + i}` },
}));
beforeEach(() => { vi.clearAllMocks(); useWorkspace.setState(base, true); });

it("loads only the latest page until older history is requested", async () => {
  vi.mocked(api.events).mockResolvedValueOnce(events(201, 100)).mockResolvedValueOnce(events(101, 100));
  await useWorkspace.getState().loadTimeline("c1");
  await useWorkspace.getState().loadTimeline("c1");
  expect(api.events).toHaveBeenCalledTimes(1);
  expect(api.events).toHaveBeenLastCalledWith("c1", { limit: 100 });
  await useWorkspace.getState().loadOlder("c1");
  expect(api.events).toHaveBeenLastCalledWith("c1", { before_seq: 201, limit: 100 });
});

it("acknowledges an empty head as a real reconnect cursor", () => {
  expect(useWorkspace.getState().lastEventId).toBeNull();
  useWorkspace.getState().applyFrame({ type: "cursor", last_id: 0 });
  expect(useWorkspace.getState().lastEventId).toBe(0);
  expect(api.events).not.toHaveBeenCalled();
});

it("refreshes an already loaded timeline after subscribing, then keeps live events", async () => {
  vi.mocked(api.events).mockResolvedValueOnce(events(201, 100)).mockResolvedValueOnce(events(202, 100));
  await useWorkspace.getState().loadTimeline("c1");
  useWorkspace.getState().applyFrame({ type: "cursor", last_id: 301 });
  useWorkspace.getState().applyFrame({ type: "event", event: events(302, 1)[0] });
  await vi.waitFor(() => expect(useWorkspace.getState().timelines.c1.loading).toBe(false));
  expect(api.events).toHaveBeenCalledTimes(2);
  expect(Object.keys(useWorkspace.getState().timelines.c1.events)).toHaveLength(101);
  expect(useWorkspace.getState().lastEventId).toBe(302);
});

it("advances the reconnect cursor when replay overflows", () => {
  useWorkspace.getState().applyFrame({ type: "resync", channels: [], last_id: 500 });
  expect(useWorkspace.getState().lastEventId).toBe(500);
});
