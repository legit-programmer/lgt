import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { WorkspaceEvent } from "../../api/types";
import type { BlockContext } from "./blocks";
import { Timeline } from "./Timeline";

interface TimelineState {
  events: Record<number, WorkspaceEvent>;
  oldestSeq: number | null;
  hasOlder: boolean;
  loading: boolean;
}

const mocks = vi.hoisted(() => ({ timeline: undefined as TimelineState | undefined }));
vi.mock("../../api/client", () => ({ api: { markRead: vi.fn(() => Promise.resolve()) } }));
vi.mock("../../store/workspace", () => ({
  useWorkspace: (selector: (state: unknown) => unknown) => selector({
    timelines: mocks.timeline ? { channel: mocks.timeline } : {},
    runs: {},
    queues: {},
    loadOlder: vi.fn(),
  }),
}));

const ctx: BlockContext = {
  channelId: "channel", isDm: false, cwd: "", agents: {}, memberIds: new Set(), handles: new Set(),
  displayName: "You", runs: {}, onReply: vi.fn(),
};

function message(seq: number): WorkspaceEvent {
  return {
    id: seq, seq, channel_id: "channel", kind: "message", ts: "2026-10-31T00:00:00Z",
    author_id: "local", author_kind: "human", run_id: null, chain_id: seq, hop: 0,
    payload: { text: `message ${seq}`, mentions: [] },
  };
}

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});
afterEach(cleanup);

describe("Timeline history skeleton", () => {
  it("shows message skeletons while the first page loads", () => {
    mocks.timeline = { events: {}, oldestSeq: null, hasOlder: true, loading: true };
    render(<Timeline channelId="channel" ctx={ctx} empty={<p>Empty</p>} />);
    expect(screen.getByRole("status", { name: "Loading earlier messages" }).querySelectorAll(".skeleton-msg")).toHaveLength(4);
  });

  it("shows skeletons above loaded messages while an older page loads", () => {
    mocks.timeline = { events: { 150: message(150) }, oldestSeq: 150, hasOlder: true, loading: true };
    render(<Timeline channelId="channel" ctx={ctx} empty={<p>Empty</p>} />);
    const skeleton = screen.getByRole("status", { name: "Loading earlier messages" });
    expect(skeleton.querySelectorAll(".skeleton-msg")).toHaveLength(2);
    expect(skeleton.compareDocumentPosition(screen.getByText("message 150")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the scroll hint instead of skeletons when idle", () => {
    mocks.timeline = { events: { 150: message(150) }, oldestSeq: 150, hasOlder: true, loading: false };
    render(<Timeline channelId="channel" ctx={ctx} empty={<p>Empty</p>} />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("Scroll up for earlier messages")).toBeTruthy();
  });
});
