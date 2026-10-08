import { describe, expect, it } from "vitest";
import type { WorkspaceEvent } from "../api/types";
import { buildTimeline, toolGroupSummary, type RunBlock } from "./timeline";

let id = 0;
function ev(seq: number, kind: string, payload: Record<string, unknown>, extra: Partial<WorkspaceEvent> = {}): WorkspaceEvent {
  return {
    id: ++id, channel_id: "c1", seq, ts: `2026-10-08T10:00:${String(seq).padStart(2, "0")}Z`, kind,
    author_kind: "system", author_id: "system", run_id: null, chain_id: 1, hop: 0, payload, ...extra,
  };
}
const human = (seq: number, text: string) => ev(seq, "message", { text, mentions: [] }, { author_kind: "human", author_id: "local" });
const agentMsg = (seq: number, run: string, text: string) =>
  ev(seq, "message", { text, mentions: [] }, { author_kind: "agent", author_id: "a1", run_id: run });
const call = (seq: number, run: string, callId: string, tool: string) =>
  ev(seq, "tool_call", { tool_call_id: callId, tool, label: tool, summary: `${tool} thing` }, { author_kind: "agent", author_id: "a1", run_id: run });
const result = (seq: number, run: string, callId: string, isError = false) =>
  ev(seq, "tool_result", { tool_call_id: callId, is_error: isError, duration_ms: 100 }, { author_kind: "agent", author_id: "a1", run_id: run });
const status = (seq: number, run: string, value: string) =>
  ev(seq, "run_status", { run_id: run, agent_id: "a1", status: value }, { run_id: run });

describe("buildTimeline", () => {
  it("groups a run's messages and tools into one block", () => {
    const blocks = buildTimeline([
      human(1, "do it"),
      status(2, "r1", "queued"),
      call(3, "r1", "t1", "read"),
      result(4, "r1", "t1"),
      call(5, "r1", "t2", "bash"),
      result(6, "r1", "t2", true),
      agentMsg(7, "r1", "done"),
      status(8, "r1", "completed"),
    ], { r1: { status: "completed", agent_id: "a1" } });
    expect(blocks.map((b) => b.type)).toEqual(["human", "run"]);
    const run = blocks[1] as RunBlock;
    expect(run.messages.map((m) => m.payload.text)).toEqual(["done"]);
    expect(run.tools).toHaveLength(2);
    expect(run.tools[1].result?.payload.is_error).toBe(true);
    expect(run.live).toBe(false);
    const summary = toolGroupSummary(run.tools);
    expect(summary).toMatchObject({ count: 2, parts: ["read", "bash"], errors: 1, durationMs: 200 });
  });

  it("shows an active run without output as a live block", () => {
    const blocks = buildTimeline([human(1, "go"), status(2, "r1", "queued")], { r1: { status: "running", agent_id: "a1" } });
    expect(blocks[1]).toMatchObject({ type: "run", live: true, agentId: "a1" });
  });

  it("splits a run around a human message and keeps the live part last", () => {
    const blocks = buildTimeline([
      status(1, "r1", "running"),
      agentMsg(2, "r1", "first"),
      human(3, "interrupt"),
      agentMsg(4, "r1", "second"),
    ], { r1: { status: "running", agent_id: "a1" } });
    expect(blocks.map((b) => b.type)).toEqual(["run", "human", "run"]);
    expect((blocks[0] as RunBlock).live).toBe(false);
    expect((blocks[2] as RunBlock).live).toBe(true);
  });

  it("applies edits and marks queued and routing deliveries", () => {
    const blocks = buildTimeline(
      [human(1, "draft"), ev(2, "message_edit", { target_seq: 1, text: "final" }, { author_kind: "human" }), human(3, "later")],
      {},
      [{ queue_id: 1, event_seq: 3, agent_id: "a2", state: "awaiting_agent", created_at: "" },
       { queue_id: 2, event_seq: 1, agent_id: null, state: "awaiting_route", created_at: "" }],
    );
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({ type: "human", text: "final", edited: true, awaitingRoute: true });
    expect(blocks[1]).toMatchObject({ type: "human", queuedFor: ["a2"], cont: true });
  });

  it("renders failures, dividers and notices, and hides finished empty runs", () => {
    const blocks = buildTimeline([
      status(1, "r1", "queued"),
      status(2, "r1", "failed"),
      ev(3, "context_reset", {}, { author_kind: "human" }),
      ev(4, "member_added", { agent_id: "a1", handle: "coder" }, { author_kind: "human" }),
      ev(5, "routing_decision", { agents: [], reason_code: "none", reason: "nobody" }),
    ], { r1: { status: "failed", agent_id: "a1" } });
    expect(blocks.map((b) => b.type)).toEqual(["run_end", "divider", "notice", "routing"]);
  });
});
