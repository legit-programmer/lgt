---
id: 20261008-routing
title: Routing
tags: [backend, routing]
created: 2026-10-08
updated: 2026-10-18
related: [20261008-dispatch-and-queue, 20261008-process-hosting, 20261008-websocket-protocol, 20261012-message-replies, 20261013-skill-invocation]
summary: Shared channel ownership, required primary selection, inline handoff/delegation mentions, and completion-only dispatch.
---

# Routing

> Summary: Shared channel ownership, required primary selection, inline handoff/delegation mentions, and completion-only dispatch.

## Files

- `lgt/orchestrator.py`: `send_message`, `_set_owner`, `_output`, and `_accept_handoffs`.
- `lgt/store.py`: `routing_state`, `set_primary_agent`, and `transfer_task_owner`.
- `lgt/transfers.py`: `parse_transfer`, the explicit transfer envelope shared by harnesses.
- `lgt/context.py`: `render_turn`, the current roster/policy/assigned-message block.

## Channel ownership

- `channels.primary_agent_id`, `ownership_version`, and `allow_handoff` persist one shared owner for every participant. Completing a task leaves it in place.
- Explicit user selection updates ownership; multiple mentions remember the last recipient. Mentions always dispatch directly.
- Replying to an agent automatically selects its author unless explicit recipients/known mentions in the actual reply override it. Quoted text never supplies mentions; unavailable source agents reject the send. See [Message replies](message-replies.md) for snapshots and selected text.
- Unmentioned messages dispatch directly to a valid primary, writing `method: "primary"` without an LLM router call. Busy-primary follow-ups queue normally.
- New channels require at least one agent and an explicit primary from those members. `PATCH /channels/{id}` accepts `primary_agent_id` for later selections.
- Legacy channels without an eligible primary report `routing_mode: unassigned` and reject conversation sends until the user selects a member. DMs retain their single recipient.
- Independent overlapping tasks do not change dispatch: unmentioned messages always go to the primary.
- Delegation inherits `task_owner_id` from its parent. Coalescing keeps deliveries with different task owners separate and gives each handoff its own turn.
- Only user selection and accepted handoff append `ownership_changed`. In-flight handoffs cannot supersede a newer ownership version.

## Handoff and delegation

Explicit [skill invocations](skill-invocation.md) route to one validated executor with `method`/`reason_code: "skill"`. The primary is the default when eligible; other agents require user selection. This dispatch preserves primary ownership and isolates the invocation in its own queue batch.

An agent includes `<@agent_id:handoff>` or `<@agent_id:delegation>` in normal prose. Targets accept member IDs or handles. The backend parses completed `message` outputs, never streaming `text_delta` events, and preserves the full message as task context. Code examples, blockquotes, and escaped markers do not dispatch work. Multiple delegation targets are supported, with at most one handoff per message and one transfer per target. Invalid messages fail before any recipient is dispatched. The desktop renders known targets as `@handle`.

The complete `lgt-transfer` fenced JSON format remains supported, containing `mode` (`handoff` or `delegation`), `target`, and `text`. Custom harnesses can alternatively send a structured `transfer` on `message`. Committed transfers expose a `transfers` array with resolved targets, source and ownership version; single transfers also expose the legacy `transfer` object. Assigned-message context includes the transfer metadata. Human messages cannot issue transfer controls.

Ordinary agent mentions and explicit delegation dispatch while preserving ownership. A handoff request must come from the current primary's current ownership version, with `allow_handoff` enabled and `routing_mode: primary`. It queues as part of the parent task. The receiver's `run_started` accepts the delivery for execution; `_accept_handoffs` then atomically updates ownership and the transferred chain's activity attribution. New selections, disabled policy, and removed receivers prevent a pending ownership transfer. Already delivered work remains delegation if superseded. Cancellation or failure before acceptance does not transfer ownership. Every transfer respects the hop limit.

`allow_handoff` defaults to true; users toggle it through channel actions or `PATCH /channels/{id}`. The channel header displays `routing_mode` from the backend. `agent_transfer` logs requested, accepted, and rejected transfers; progress and completion never select owners. See [the exact API contract](../../../docs/backend-reference.md#channel-changes).

## `routing_decision` payload

Direct dispatch records `method` and `reason_code` as `mention`, `primary`, or `skill`, with `for_seqs`, recipient `agents`, and a human-readable `reason`. Historical router events remain readable in the append-only log. No model router, random fallback, or generated starter suggestions remain.

## Related

- [Dispatch and queue](dispatch-and-queue.md) — how deliveries reach agents.
- [Process hosting](process-hosting.md) — `invoke_cli` safety limits.
- [WebSocket protocol](websocket-protocol.md) — how decisions reach the UI.
