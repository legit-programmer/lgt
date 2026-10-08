import { beforeEach, describe, expect, it } from "vitest";
import type { WorkspaceEvent } from "../api/types";
import { useWorkspace } from "./workspace";

const base = useWorkspace.getState();

function event(seq: number, kind: string, payload: Record<string, unknown>, extra: Partial<WorkspaceEvent> = {}): WorkspaceEvent {
  return {
    id: seq, channel_id: "c1", seq, ts: "2026-10-08T10:00:00Z", kind, author_kind: "system",
    author_id: "system", run_id: null, chain_id: 1, hop: 0, payload, ...extra,
  };
}

describe("workspace frames", () => {
  beforeEach(() => {
    useWorkspace.setState({ ...base, timelines: { c1: { events: {}, oldestSeq: null, hasOlder: false, loading: false } }, partials: {}, runs: {}, lastEventId: 0 });
  });

  it("appends events to loaded timelines and advances the cursor", () => {
    useWorkspace.getState().applyFrame({ type: "event", event: event(4, "message", { text: "hi", mentions: [] }) });
    useWorkspace.getState().applyFrame({ type: "event", event: event(9, "message", { text: "elsewhere", mentions: [] }, { channel_id: "c2" }) });
    const state = useWorkspace.getState();
    expect(Object.keys(state.timelines.c1.events)).toEqual(["4"]);
    expect(state.timelines.c2).toBeUndefined();
    expect(state.lastEventId).toBe(9);
  });

  it("streams deltas and clears them when the run commits or ends", () => {
    const apply = useWorkspace.getState().applyFrame;
    apply({ type: "event", event: event(1, "run_status", { run_id: "r1", agent_id: "a1", status: "running", started_at: "x" }, { run_id: "r1" }) });
    apply({ type: "delta", run_id: "r1", channel_id: "c1", text: "Hel" });
    apply({ type: "delta", run_id: "r1", channel_id: "c1", text: "lo" });
    expect(useWorkspace.getState().partials.r1.text).toBe("Hello");
    apply({ type: "event", event: event(2, "message", { text: "Hello", mentions: [] }, { run_id: "r1", author_kind: "agent", author_id: "a1" }) });
    expect(useWorkspace.getState().partials.r1).toBeUndefined();
    apply({ type: "partial_snapshot", run_id: "r1", channel_id: "c1", text: "More" });
    apply({ type: "event", event: event(3, "run_status", { run_id: "r1", agent_id: "a1", status: "completed" }, { run_id: "r1" }) });
    const state = useWorkspace.getState();
    expect(state.partials.r1).toBeUndefined();
    expect(state.runs.r1).toMatchObject({ status: "completed", agent_id: "a1", channel_id: "c1" });
  });

  it("stores flattened snapshot frames", () => {
    const apply = useWorkspace.getState().applyFrame;
    apply({ type: "queue", channel_id: "c1", items: [{ queue_id: 1, event_seq: 3, agent_id: "a1", state: "awaiting_agent", created_at: "" }] });
    apply({ type: "agent_status", agent_id: "a1", state: "working", active_runs: [{ run_id: "r9", channel_id: "c1", started_at: "t" }], activity: null, last_failure: null });
    apply({ type: "me", human_id: "local", display_name: "Sam" });
    const state = useWorkspace.getState();
    expect(state.queues.c1).toHaveLength(1);
    expect(state.statuses.a1.state).toBe("working");
    expect(state.runs.r9).toMatchObject({ agent_id: "a1", started_at: "t" });
    expect(state.me?.display_name).toBe("Sam");
  });
});
