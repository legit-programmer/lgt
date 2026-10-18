---
id: 20261008-dispatch-and-queue
title: Dispatch and queue
tags: [backend, runs, routing]
created: 2026-10-08
updated: 2026-10-18
related: [20261008-run-lifecycle, 20261008-routing, 20261008-cancel-retracts-message, 20261008-event-store, 20261008-context-and-sessions]
summary: How the orchestrator serializes each channel through a mailbox, moves deliveries through queue states, coalesces messages for busy agents, and starts runs.
---

# Dispatch and queue

> Summary: How the orchestrator serializes each channel through a mailbox, moves deliveries through queue states, coalesces messages for busy agents, and starts runs.

## Mailboxes

`ChannelMailbox` (`lgt/orchestrator.py`) is a per-channel asyncio queue of synchronous operations. Every write to a channel goes through `Orchestrator._call(channel_id, op)`: sending, editing, primary selection, run output, finishing a run, cancelling a delivery, changing the cwd, and membership changes. Operations on one channel are therefore strictly ordered, while different channels proceed in parallel.

## Queue states (`dispatch_queue.state`)

| State | Meaning |
| --- | --- |
| `awaiting_route` | Legacy storage state only; the pump cancels these items with a visible notice to select a primary and resend. New sends never create it. |
| `awaiting_agent` | Waiting for a specific agent to be free. |
| `dispatched` | Delivered into a run. |
| `dropped` | Legacy terminal state for an undelivered item. |
| `cancelled` | Cancelled by a user, a member removal, or an archive. |

## The pump (`_pump` → `_pump_queue`)

`_pump` runs after every relevant change. It dispatches ready deliveries and publishes queue state:

1. It groups `awaiting_agent` items by idle agent and task owner and calls `_dispatch` for the first owner's group. **Coalescing:** queued messages for the same recipient and owner become one turn, with `trigger_seq` set to the newest one. Independent user work stays separate from delegated work for that recipient. Each handoff gets its own turn; surrounding delegation stays queued until its proper turn.
2. It publishes a `queue` frame when the pending list changed (`_publish_queue`).

## Dispatch (`_dispatch`)

1. It resolves the session plan, resume or cold ([context](context-and-sessions.md)).
2. It inserts a `Run` with `status="queued"`. The unique key `(channel_id, trigger_seq, agent_id)` makes dispatch idempotent.
3. It appends the `queued` `run_status` event and marks the queue items `dispatched`.
4. It builds the `Turn`: the rendered prompt plus the attachments of the triggering messages.
5. It starts `_execute` as a task ([run lifecycle](run-lifecycle.md)).

## Rules worth knowing

- **One active run per agent per channel.** Different agents in a channel run in parallel. A global `asyncio.Semaphore(concurrent_runs)` caps all runs; a run waiting on it stays `queued`.
- **Unmentioned messages use the channel primary directly**, including during independent overlapping work. Channels without an eligible primary reject sends. A busy recipient gets an `awaiting_agent` item.
- **Agent mentions delegate:** an agent message that @mentions another member enqueues it with the parent `task_owner_id` and `hop + 1`. Explicit `lgt-transfer` messages distinguish delegation from ownership handoff. At `max_hops` a `system` notice stops the chain. See [routing](routing.md).
- **DMs always dispatch to their single agent**.
- **Slash commands run on the server:** `/new`, `/cwd <path>` and `/cancel [run_id]`. They are parsed in `send_message`; the registry is in `lgt/services.py`.

## Related

- [Run lifecycle](run-lifecycle.md) — what happens after dispatch.
- [Routing](routing.md) — primary selection and agent transfers.
- [Cancel retracts message](../decisions/cancel-retracts-message.md) — semantics of `cancel_delivery`.
- [Event store](event-store.md) — the tables involved.
