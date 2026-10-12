import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MessagePayload, WorkspaceEvent } from "../../api/types";
import { HumanMessage, RunSegment, type BlockContext } from "./blocks";
import { Composer } from "./Composer";
import type { ReplyDraft } from "./ReplyQuote";

const mocks = vi.hoisted(() => ({ sendMessage: vi.fn(), commands: vi.fn(), reportError: vi.fn() }));
vi.mock("../../api/client", () => ({ api: { sendMessage: mocks.sendMessage, commands: mocks.commands } }));
vi.mock("../../store/workspace", () => ({
  reportError: mocks.reportError,
  useWorkspace: (selector: (state: { partials: object }) => unknown) => selector({ partials: {} }),
}));

const message: WorkspaceEvent<MessagePayload> = {
  id: 1, seq: 1, channel_id: "channel", kind: "message", ts: "2026-10-11T00:00:00Z",
  author_id: "local", author_kind: "human", run_id: null, chain_id: 1, hop: 0,
  payload: { text: "Choose **option B** today.", mentions: [] },
};
const ctx: BlockContext = {
  channelId: "channel", agents: {}, memberIds: new Set(), handles: new Set(),
  displayName: "You", runs: {}, onReply: vi.fn(),
};
const draft: ReplyDraft = {
  reply_to_seq: 1, reply_selection: "option B",
  quote: { seq: 1, author_id: "beta", author_kind: "agent", author_handle: "beta",
    text: "option B", selected: true, truncated: false },
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.commands.mockResolvedValue([]);
  mocks.sendMessage.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  window.getSelection()?.removeAllRanges();
});

function select(node: Node) {
  const range = document.createRange();
  range.selectNodeContents(node);
  window.getSelection()?.removeAllRanges();
  window.getSelection()?.addRange(range);
  fireEvent(document, new Event("selectionchange"));
}

function renderHuman() {
  return render(<HumanMessage ctx={ctx} block={{ type: "human", key: "msg:1", event: message,
    text: message.payload.text, edited: false, deleted: false, attachments: [], queuedFor: [],
    awaitingRoute: false, cont: false }} />);
}

function renderComposer(onClearReply = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>
    <Composer channelId="reply-test" placeholder="Message" members={[]} allowMentions
      reply={draft} replyLoading={false} displayName="You" onClearReply={onClearReply} />
  </QueryClientProvider>);
}

describe("message replies", () => {
  it("offers whole-message and selected-text replies using rendered Markdown text", () => {
    const { container } = renderHuman();
    fireEvent.click(screen.getByRole("button", { name: "Reply to message #1" }));
    expect(ctx.onReply).toHaveBeenLastCalledWith(1);
    select(container.querySelector("strong")!);
    fireEvent.click(screen.getByRole("button", { name: "Reply to selected text in message #1" }));
    expect(ctx.onReply).toHaveBeenLastCalledWith(1, "option B");
  });

  it("does not offer selected-text replies for tool outputs or selections spanning messages", () => {
    const agentMessage = { ...message, seq: 2, author_kind: "agent" as const, author_id: "beta" };
    const { container } = render(<RunSegment ctx={ctx} block={{
      type: "run", key: "run", runId: null, agentId: "beta", seq: 2, ts: message.ts,
      messages: [agentMessage, { ...agentMessage, seq: 3 }], live: false, status: "completed", cont: false,
      tools: [{ call: { ...message, seq: 4, kind: "tool_call", payload: { tool_call_id: "read", name: "Read" } },
        result: { ...message, seq: 5, kind: "tool_result", payload: { tool_call_id: "read", output: "TOOL OUTPUT", is_error: false } } }],
    }} />);
    select(container.querySelector(".fv-tools")!);
    expect(screen.queryByRole("button", { name: /Reply to selected text/ })).toBeNull();
    const bodies = container.querySelectorAll(".fv-message-text");
    const range = document.createRange();
    range.setStart(bodies[0], 0);
    range.setEnd(bodies[1], 1);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent(document, new Event("selectionchange"));
    expect(screen.queryByRole("button", { name: /Reply to selected text/ })).toBeNull();
  });

  it("sends reply metadata separately from new text and clears the draft on success", async () => {
    const clear = vi.fn();
    renderComposer(clear);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "implement it" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(clear).toHaveBeenCalledOnce());
    expect(mocks.sendMessage).toHaveBeenCalledWith("reply-test", {
      text: "implement it", attachments: [], reply_to_seq: 1, reply_selection: "option B",
    });
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
  });

  it("retains text and quote when the backend rejects a reply", async () => {
    mocks.sendMessage.mockRejectedValueOnce(new Error("agent is unavailable"));
    const clear = vi.fn();
    renderComposer(clear);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(mocks.reportError).toHaveBeenCalledOnce());
    expect(clear).not.toHaveBeenCalled();
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("keep this draft");
    expect(screen.getByText("option B")).toBeTruthy();
  });
});
