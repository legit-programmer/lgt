---
id: 20261008-timeline-model
title: Timeline model
tags: [desktop, ui]
created: 2026-10-08
updated: 2026-10-25
related: [20261008-client-state, 20261008-screens, 20261008-event-store, 20261008-run-lifecycle, 20261012-message-replies, 20261025-focus-mode]
summary: The rules buildTimeline uses to turn a channel's events into blocks — human messages, run segments with tool groups, routing notices, run failures, dividers, notices — and how the Timeline component scrolls and marks read.
---

# Timeline model

> Summary: The rules buildTimeline uses to turn a channel's events into blocks — human messages, run segments with tool groups, routing notices, run failures, dividers, notices — and how the Timeline component scrolls and marks read.

## Files

- `desktop/src/lib/timeline.ts`: `buildTimeline(events, runs, queue)`, `toolGroupSummary` and `toolName`. It is pure and tested in `timeline.test.ts`.
- `desktop/src/features/channel/blocks.tsx`: one component per block type.
- `desktop/src/features/channel/Timeline.tsx`: scrolling, paging, anchors and read cursor.

## Block rules

| Block | From | Notes |
| --- | --- | --- |
| `human` | Human `message` | `message_edit` events are applied (edited text, `deleted`). A `queue` item marks it `queuedFor` (`awaiting_agent`) or `awaitingRoute`, which renders the dashed queued style with Cancel. Deleted messages are hidden. |
| `run` | Agent `message`, `tool_call`, `tool_result` and `tool_summary` events with the same `run_id` | One block per **segment** of a run. A segment ends at a human message or a context reset, so later output appears after the interruption. A run with no output yet still gets a block at its `queued`/`running` status event. |
| `routing` | `routing_decision` | Recipient chips and reason. Historical router decisions remain readable; historical suggestions are text only. |
| `run_end` | Terminal `run_status` that is `failed` or `cancelled` | Failure uses the server's `text`. Cancellation shows the duration. |
| `divider` | `context_reset`, `context_checkpoint` | |
| `notice` | `member_added`, `member_removed`, `cwd_changed`, `channel_changed`, `delivery_cancelled`, `ownership_changed`, `agent_transfer`, `system` | Ownership selections and transfer outcomes stay visible in history. |

- **Live segment:** the last segment of a run whose status is `queued`, `starting` or `running` is live. It shows the working badge with an elapsed clock, the partial text with a caret, the last three tool rows, and Stop.
- **Tool groups:** finished segments with two or more tools collapse into "ran N tools · read · bash ×2 · pass/err · duration". Each child row expands to its output.
- **Quiet summaries:** `tool_summary` supplies `RunBlock.toolSummary` and renders names/counts without expandable raw tools. A summary-only finished run remains visible. The backend owns suppression; see [Focus mode](../backend/focus-mode.md).
- **Continuations:** consecutive blocks from the same speaker drop the header (`cont`).
- **Hidden blocks:** empty, finished segments are dropped.
- **Replies:** committed human/agent messages offer whole-message replies and text-selection replies. Each source is a message event, rather than an entire run/tool group. Sent quotes render above the new message; nested quotes and tools are outside the selectable source body.
- **Transfer mentions:** `Markdown` renders `<@agent_id:handoff>` and `<@agent_id:delegation>` as `@handle` using the backend's agent roster. Code examples stay literal. Rendering never dispatches work; the backend processes completed agent messages.

## Timeline component behavior

- **Pinned to the bottom:** a `ResizeObserver` keeps the view at the bottom while streaming, unless the user has scrolled up.
- **Composer overlap:** the composer floats over the bottom of the timeline. `ChannelScreen` publishes its height as `--composer-h`, and `.timeline-inner` pads by that amount, so the newest message rests just above it.
- **Paging:** scrolling near the top loads older pages, and CSS `overflow-anchor` keeps the position steady.
- **Anchors:** palette search results open the channel with `anchorSeq`. The store pages back until that seq is loaded, then scrolls to it and highlights it.
- **Read cursor:** `POST /channels/{id}/read` is sent, with a short debounce, when the newest seq is visible and the window is in view.
- **Performance:** blocks use `content-visibility: auto` rather than a virtual list.

## Related

- [Message replies](../backend/message-replies.md) — author targeting, backend previews and composer drafts.

- [Client state](client-state.md) — where events, runs and queues come from.
- [Screens](screens.md) — the views that host the timeline.
- [Event store](../backend/event-store.md) — event kinds.
- [Run lifecycle](../backend/run-lifecycle.md) — run statuses that drive live segments.
