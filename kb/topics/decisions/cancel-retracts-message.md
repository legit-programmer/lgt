---
id: 20261008-cancel-retracts-message
title: "Decision: cancelling a queued message can retract it"
tags: [decision, backend, runs]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-dispatch-and-queue, 20261008-timeline-model]
summary: Semantics of cancel_delivery — which queue items it cancels, when it also deletes the message from every agent's future context, and how it interacts with in-flight routing.
---

# Decision: cancelling a queued message can retract it

> Summary: Semantics of cancel_delivery — which queue items it cancels, when it also deletes the message from every agent's future context, and how it interacts with in-flight routing.

## Context

A message to a busy agent is already a durable event; only its delivery is pending. The design shows such a message as "queued → reviewer · sends when it's free · Cancel", and users expect Cancel to make it disappear.

## Decision (`Orchestrator.cancel_delivery`)

- `POST /channels/{id}/messages/{seq}/cancel` (or the `cancel_delivery` WebSocket command) marks the message's pending queue items `cancelled`. Optional `agent_ids` limits it to some recipients.
- With no `agent_ids`, a pending `awaiting_route` item is cancelled too, and `_apply_route` discards the router's answer when it arrives.
- If no agent has received the local human's message, and none will, the message is **retracted**: a `message_edit` with `deleted: true` removes it from every agent's future context.
- A `delivery_cancelled` event records `target_seq`, `agent_ids` and `retracted`.

## Consequences

- Cancelling a fully queued message removes it from the UI and from every agent's prompt.
- Cancelling one recipient of a message that another agent already received only stops that delivery.
- If an agent's session had already seen the message as passive context, the deletion edit makes that session rebuild cold.

## Related

- [Dispatch and queue](../backend/dispatch-and-queue.md) — queue states.
- [Timeline model](../desktop/timeline-model.md) — how queued and deleted messages render.
