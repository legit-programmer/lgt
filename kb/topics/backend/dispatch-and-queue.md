---
id: 20261008-dispatch-and-queue
title: Dispatch and queue
tags: [backend, runs, routing]
created: 2026-10-08
updated: 2026-10-11
related: [20261008-run-lifecycle, 20261008-routing, 20261008-cancel-retracts-message, 20261008-event-store, 20261008-context-and-sessions]
summary: How the orchestrator serializes each channel through a mailbox, moves deliveries through queue states, coalesces messages for busy agents, and starts runs.
---

# Dispatch and queue

> Summary: How the orchestrator serializes each channel through a mailbox, moves deliveries through queue states, coalesces messages for busy agents, and starts runs.

## Mailboxes

`ChannelMailbox` (`lgt/orchestrator.py`) is a per-channel asyncio queue of synchronous operations. Every write to a channel goes through `Orchestrator._call(channel_id, op)`: sending, editing, routing results, run output, finishing a run, cancelling a delivery, changing the cwd, and membership changes. Operations on one channel are therefore strictly ordered, while different channels proceed in parallel.

## Queue states (`dispatch_queue.state`)

| State | Meaning |
| --- | --- |
| `awaiting_route` | An unmentioned message with no eligible primary, or independent tasks overlapping, waiting for routing. `agent_id` is null. |
| `awaiting_agent` | Waiting for a specific agent to be free. |
| `dispatched` | Delivered, either into a run or into routing results. |
| `dropped` | The router chose nobody. |
| `cancelled` | Cancelled by a user, a member removal, or an archive. |

## The pump (`_pump` → `_pump_queue`)

`_pump` runs after every relevant change. It does three things:

1. If ready `awaiting_route` items exist and no route task is running for the channel, it starts `_route` with a roster of members, each marked `busy`.
2. It groups `awaiting_agent` items by idle agent and task owner and calls `_dispatch` for the first owner's group. **Coalescing:** queued messages for the same recipient and owner become one turn, with `trigger_seq` set to the newest one. Independent user work stays separate from delegated work for that recipient. Each handoff gets its own turn; surrounding delegation stays queued until its proper turn.
3. It publishes a `queue` frame when the pending list changed (`_publish_queue`).

`_apply_route` re-reads queue state before applying a decision. Items cancelled meanwhile, and agents removed meanwhile, are skipped.

## Dispatch (`_dispatch`)

1. It resolves the session plan, resume or cold ([context](context-and-sessions.md)).
2. It inserts a `Run` with `status="queued"`. The unique key `(channel_id, trigger_seq, agent_id)` makes dispatch idempotent.
3. It appends the `queued` `run_status` event and marks the queue items `dispatched`.
4. It builds the `Turn`: the rendered prompt plus the attachments of the triggering messages.
5. It starts `_execute` as a task ([run lifecycle](run-lifecycle.md)).

## Rules worth knowing

- **One active run per agent per channel.** Different agents in a channel run in parallel. A global `asyncio.Semaphore(concurrent_runs)` caps all runs; a run waiting on it stays `queued`.
- **Unmentioned messages use the channel primary directly** when one is eligible and independent tasks do not overlap. Otherwise they route immediately, even while agents are busy. A busy recipient gets an `awaiting_agent` item.
- **Agent mentions delegate:** an agent message that @mentions another member enqueues it with the parent `task_owner_id` and `hop + 1`. Explicit `lgt-transfer` messages distinguish delegation from ownership handoff. At `max_hops` a `system` notice stops the chain. See [routing](routing.md).
- **DMs always dispatch to their single agent**, without the router.
- **Slash commands run on the server:** `/new`, `/cwd <path>` and `/cancel [run_id]`. They are parsed in `send_message`; the registry is in `lgt/services.py`.

## Related

- [Run lifecycle](run-lifecycle.md) — what happens after dispatch.
- [Routing](routing.md) — how `awaiting_route` items get decided.
- [Cancel retracts message](../decisions/cancel-retracts-message.md) — semantics of `cancel_delivery`.
- [Event store](event-store.md) — the tables involved.
