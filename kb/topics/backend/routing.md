---
id: 20261008-routing
title: Routing
tags: [backend, routing]
created: 2026-10-08
updated: 2026-10-13
related: [20261008-dispatch-and-queue, 20261008-process-hosting, 20261008-websocket-protocol, 20261012-message-replies, 20261013-skill-invocation]
summary: Shared channel ownership, direct follow-ups, handoff versus delegation, router fallback during independent overlapping work, and model-routing contracts.
---

# Routing

> Summary: Shared channel ownership, direct follow-ups, handoff versus delegation, router fallback during independent overlapping work, and model-routing contracts.

## Files

- `lgt/router.py`: `CLIRouter`, prompt building, and output parsing.
- `lgt/orchestrator.py`: `send_message`, `_set_owner`, `_route`, `_apply_route`, `_output`, and `_accept_handoffs`.
- `lgt/store.py`: `routing_state`, `set_primary_agent`, and `transfer_task_owner`.
- `lgt/transfers.py`: `parse_transfer`, the explicit transfer envelope shared by harnesses.
- `lgt/context.py`: `render_turn`, the current roster/policy/assigned-message block.

## Channel ownership

- `channels.primary_agent_id`, `ownership_version`, and `allow_handoff` persist one shared owner for every participant. Completing a task leaves it in place.
- Explicit user selection updates ownership; multiple mentions remember the last recipient. Mentions always dispatch directly.
- Replying to an agent automatically selects its author unless explicit recipients/known mentions in the actual reply override it. Quoted text never supplies mentions; unavailable source agents reject the send. See [Message replies](message-replies.md) for snapshots and selected text.
- Unmentioned messages dispatch directly to a valid primary, writing `method: "primary"` without an LLM router call. Busy-primary follow-ups queue normally.
- Fresh or unavailable-owner channels use the router. Independent active user tasks across multiple owners also use it. `Store.routing_state` counts runs and pending agent deliveries, including those waiting on the global semaphore.
- Delegation inherits `task_owner_id` from its parent. Multiple agents collaborating on one task do not activate router mode. Coalescing keeps deliveries with different task owners separate and gives each handoff its own turn.
- A router assignment remembers the first eligible recipient. Once overlap ends, the remembered owner resumes, regardless of which agent finished last.
- Only user selection, accepted handoff, and router assignment append `ownership_changed`. In-flight routing results cannot supersede a newer ownership version.

## Handoff and delegation

Explicit [skill invocations](skill-invocation.md) route to one validated executor with `method`/`reason_code: "skill"`. The primary is the default when eligible; other agents require user selection. This dispatch preserves primary ownership, skips the model router, and isolates the invocation in its own queue batch.

An agent emits a complete `lgt-transfer` fenced JSON message containing `mode` (`handoff` or `delegation`), `target` (member handle or ID), and `text` (the task and context). `parse_transfer` does not interpret quoted examples or human messages. Custom harnesses can alternatively send a structured `transfer` on `message`.

Ordinary agent mentions and explicit delegation dispatch while preserving ownership. A handoff request must come from the current primary's current ownership version, with `allow_handoff` enabled and `routing_mode: primary`. Specialists delegate while router mode is active. It queues as part of the parent task. The receiver's `run_started` accepts the delivery for execution; `_accept_handoffs` then atomically updates ownership and the transferred chain's activity attribution. New selections, disabled policy, and removed receivers prevent a pending ownership transfer. Already delivered work remains delegation if superseded. Cancellation or failure before acceptance does not transfer ownership. Every transfer respects the hop limit.

`allow_handoff` defaults to true; users toggle it through channel actions or `PATCH /channels/{id}`. The channel header displays `routing_mode` from the backend. `agent_transfer` logs requested, accepted, and rejected transfers; progress and completion never select owners. See [the exact API contract](../../../docs/backend-reference.md#channel-changes).
- `lgt/oneshot.py`: `invoke_cli`, which runs the router CLIs without a shell and with bounded output.

## Model routing

1. `_pump` builds a `RoutingRequest`: the channel, a roster (`agent_id`, handle, description, and `busy` for each member, plus outside agents as candidates for suggestions), the last `router_context_events` events as cold-rendered context, and the messages to route.
2. `CLIRouter.route` asks `claude -p` with `router_model` (default `haiku`), with tools disabled and `--dangerously-skip-permissions`. If that fails, it falls back to `codex exec --ephemeral`. There are `router_attempts` tries per provider, each bounded by `router_timeout_seconds`.
3. The model must return strict JSON with `agents`, `reason` and optionally `suggested_agents`. An empty `agents` list is valid.
4. If both providers fail, a random channel member takes the message (`reason_code: "router_failed_random"`, with the error recorded).
5. `_apply_route` appends a `routing_decision` event and enqueues the chosen members. Outside agents are suggestions only and are never dispatched.

## `routing_decision` payload

```json
{"for_seqs": [12], "agents": ["…"], "suggested_agents": ["…"],
 "method": "router" | "mention" | "primary", "reason_code": "router" | "mention" | "primary" | "router_failed_random" | "none",
 "reason": "free text", "error": "optional"}
```

Explicit mentions skip the model and write `method: "mention"`, `reason: "explicit mentions"`. The UI renders "routed → none · reason" with **Add &lt;agent&gt;** buttons for the suggestions.

## Suggestions ("Try asking")

`GET /channels/{id}/suggestions` → `Orchestrator.channel_suggestions` asks the router model for three starter prompts based on the roster's descriptions. The result is cached per roster, and concurrent requests share one in-flight task.

## Related

- [Dispatch and queue](dispatch-and-queue.md) — where `awaiting_route` items come from.
- [Process hosting](process-hosting.md) — `invoke_cli` safety limits.
- [WebSocket protocol](websocket-protocol.md) — how decisions reach the UI.
