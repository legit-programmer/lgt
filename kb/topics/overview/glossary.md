---
id: 20261008-glossary
title: Glossary
tags: [overview]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-system-overview, 20261008-event-store, 20261008-dispatch-and-queue, 20261008-context-and-sessions]
summary: Definitions of the domain terms (agent, harness, channel, event, seq, chain, hop, run, session, delivery, checkpoint) as the code uses them.
---

# Glossary

> Summary: Definitions of the domain terms (agent, harness, channel, event, seq, chain, hop, run, session, delivery, checkpoint) as the code uses them.

## Terms

| Term | Meaning | Code |
| --- | --- | --- |
| Human | The single local user, id `local`, with an editable display name. | `human_profiles` table, `/me` |
| Agent | A configuration: handle, description, harness, model, system prompt, allowed tools, default cwd, avatar, hue, extra args. Retired agents keep their history. | `models.Agent` |
| Harness | The CLI behind an agent: `codex`, `claude` (alias `claude_code`), `gemini`, or `custom`. | `harnesses.py` |
| Capabilities | Booleans a harness advertises: `resume`, `interrupt`, `text_delta`, `allowed_tools`, `image_input`, `usage`, `rate_limits`. Agent settings are validated against them. | `HarnessRegistry.capabilities_for` |
| Channel | A named conversation with a working directory (cwd) and its own event log. Kind is `channel` or `dm`. | `models.Channel` |
| DM | A channel with exactly one agent, created automatically with that agent (`dm_channel_id`). | `Orchestrator._ensure_dm` |
| Managed cwd | `data_dir/workspaces/<channel_id>`, used when no directory is given. | `Settings.workspace_dir` |
| Event | An immutable row in a channel's log. It has a per-channel `seq`, a global `id`, a `kind`, an author, and a payload. | `events` table |
| seq / id | `seq` orders events within one channel; `id` orders them across all channels and is the WebSocket replay cursor (`last_id`). | `Store.append_event` |
| Chain / hop | `chain_id` links a human message to every event it causes. `hop` counts agent-to-agent mention steps; `max_hops` stops loops. | `Orchestrator._output` |
| Delivery / queue item | A pending hand-off of a message: `awaiting_route` (waiting for the router) or `awaiting_agent` (waiting for a busy agent). Later states are `dispatched`, `dropped` and `cancelled`. | `dispatch_queue` table |
| Run | One harness invocation for one agent in one channel. Statuses are `queued`, `starting`, `running`, `completed`, `failed` and `cancelled`. | `models.Run`, `runs` table |
| Turn | What a runner receives: the run, the agent, the channel, the rendered prompt, the session, and attachments. | `models.Turn` |
| Session | The harness's own conversation (`harness_session_id`) for an agent and channel pair. It is resumable only while it stays valid. | `agent_sessions` table |
| Resume / cold | Resume sends only the new events to an existing session. Cold rebuilds the prompt from the last reset or checkpoint. | `context.resolve_session` |
| Context reset | A `/new` or **Fresh context** action. It appends `context_reset`, and every session rebuilds cold after it. | `Orchestrator.new_context` |
| Checkpoint | A rolling summary of old context (`context_checkpoint`), so cold rebuilds stay bounded. | `Orchestrator._maybe_checkpoint` |
| Partial | Live text deltas of a run that have not yet been committed as a `message`. They are never stored. | `Orchestrator._partials` |
| Activity | The current action of a working agent ("Running …", "Writing response"). | `Orchestrator._set_activity` |
| Ember | The design system: dark-first, one amber accent, a glass chat column. | `design/README.md` |

## Related

- [System overview](system-overview.md) — where these terms meet.
- [Event store](../backend/event-store.md) — events, seq, chains in storage.
- [Dispatch and queue](../backend/dispatch-and-queue.md) — deliveries and runs.
- [Context and sessions](../backend/context-and-sessions.md) — resume, cold, checkpoints.
