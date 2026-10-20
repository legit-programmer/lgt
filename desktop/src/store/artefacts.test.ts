import { beforeEach, expect, it } from "vitest";
import type { ChannelSummary, ServerFrame } from "../api/types";
import { useUi } from "./ui";
import { useWorkspace } from "./workspace";
const frame: ServerFrame = { type: "artefact_open", channel_id: "c1", artefact: {
  name: "plan.md", path: "plan.md", kind: "markdown", size_bytes: 12, revision: "1", cwd: "/project",
} };
beforeEach(() => {
  useWorkspace.setState({ channels: { c1: { cwd: "/project" } as ChannelSummary }, lastEventId: 0, artefactRevision: 0 });
  useUi.setState({ view: { kind: "channel", channelId: "c1" }, detailTab: "agents", detailOpen: false, sidebarOpen: true, selectedArtefact: null });
});
it("opens creation and reopens updates, closing other panels", () => {
  useWorkspace.getState().applyFrame(frame);
  expect(useUi.getState()).toMatchObject({ detailOpen: true, detailTab: "artefacts", sidebarOpen: false });
  const generation = useUi.getState().selectedArtefact!.generation;
  useUi.getState().setDetailOpen(false);
  useWorkspace.getState().applyFrame(frame);
  expect(useUi.getState().detailOpen).toBe(true);
  expect(useUi.getState().selectedArtefact!.generation).toBeGreaterThan(generation);
});
it("does not steal focus from another channel or use a previous cwd", () => {
  useUi.setState({ view: { kind: "channel", channelId: "c2" } });
  useWorkspace.getState().applyFrame(frame);
  expect(useUi.getState().detailOpen).toBe(false);
  useUi.setState({ view: { kind: "channel", channelId: "c1" } });
  useWorkspace.setState({ channels: { c1: { cwd: "/new" } as ChannelSummary } });
  useWorkspace.getState().applyFrame(frame);
  expect(useUi.getState().detailOpen).toBe(false);
});
it("replayed announcement messages never auto-open", () => {
  useWorkspace.getState().applyFrame({ type: "event", event: { id: 1, seq: 1, channel_id: "c1", kind: "message", author_kind: "agent", author_id: "a", ts: "", run_id: null, chain_id: 1, hop: 0, payload: { artefact: frame.artefact } } });
  expect(useUi.getState().detailOpen).toBe(false);
});
it("renames and deletes the selection only after backend events", () => {
  useWorkspace.getState().applyFrame(frame);
  const event = { id: 1, seq: 1, channel_id: "c1", kind: "artefact_changed", author_kind: "human" as const, author_id: "local", ts: "", run_id: null, chain_id: 1, hop: 0, payload: { cwd: "/project", path: "plan.md", new_path: "next.md" as string | null } };
  useWorkspace.getState().applyFrame({ type: "event", event });
  expect(useUi.getState().selectedArtefact?.path).toBe("next.md");
  useWorkspace.getState().applyFrame({ type: "event", event: { ...event, id: 2, seq: 2, payload: { ...event.payload, path: "next.md", new_path: null } } });
  expect(useUi.getState().selectedArtefact).toBeNull();
});
