---
id: 20261008-event-store
title: Event store
tags: [backend, storage]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-glossary, 20261008-dispatch-and-queue, 20261008-live-state, 20261008-attachments, 20261008-mutable-channel-cwd]
summary: The SQLite schema, the append-only event log and its event kinds, triggers that enforce invariants, migrations, FTS search, and the summary and usage queries.
---

# Event store

> Summary: The SQLite schema, the append-only event log and its event kinds, triggers that enforce invariants, migrations, FTS search, and the summary and usage queries.

## Files

- `lgt/schema.sql`: tables, indexes and triggers. It is applied on every open, so every statement is idempotent (`IF NOT EXISTS`, `DROP ... IF EXISTS`).
- `lgt/store.py`: the `Store` class, a synchronous SQLite wrapper with WAL, `busy_timeout`, foreign keys, and `transaction()`, which nests through savepoints.

## Tables

| Table | Purpose |
| --- | --- |
| `agents` | Agent config. Later columns are `avatar`, `hue`, `extra_args`, `command`, `retired_at` and `dm_channel_id`. |
| `channels` | Name, kind, cwd, `cwd_managed`, `next_seq`, the checkpoint counter and `archived_at`. |
| `channel_members` | Human and agent memberships. A trigger requires agents to exist. |
| `events` | The immutable log, unique on `(channel_id, seq)`. `id` is the global cursor. |
| `runs` | Run rows, token counters, `duration_ms`, structured `error`, and context usage. |
| `agent_sessions` | Resumable session state per agent and channel. |
| `dispatch_queue` | Durable deliveries with a `state`. |
| `attachments` | Upload metadata and `message_seq` once sent. |
| `read_cursors` | The last read seq per channel and human. |
| `harness_limits` | The latest plan-limit snapshot per harness. |
| `human_profiles` | Display names. |
| `search_fts` | An FTS5 virtual table over message and tool text, created by `_migrate`. |

## Invariants enforced in SQL

- **`events_no_update` / `events_no_delete`:** the log is append-only.
- **`events_one_run_status_idx`:** a run has at most one terminal `run_status` event.
- **`attachments_bind_once` / `attachments_keep_sent`:** a sent attachment can't be rebound or deleted.
- **`channel_members_agent_exists`:** memberships must reference existing agents.

The original `channels_cwd_immutable` trigger is dropped; see [mutable channel cwd](../decisions/mutable-channel-cwd.md).

## Appending

`Store.append_event` runs under `BEGIN IMMEDIATE`. It allocates `seq` from `channels.next_seq` and predicts the `AUTOINCREMENT` id, so a human root event can carry its own `chain_id`. Events not authored by the human must pass the `chain_id` of the event that caused them. The orchestrator wraps every append in `_append`, which also maintains the checkpoint size counter and the search index.

## Event kinds

| Kind | Author | Purpose |
| --- | --- | --- |
| `message` | Human or agent | Text, mentions and attachments |
| `message_edit` | Human | Edits or deletes an earlier message. The original is never changed. |
| `tool_call`, `tool_result` | Agent | Normalized tool activity |
| `run_status` | System | Run lifecycle |
| `routing_decision` | Router | Who receives a message, and why |
| `context_reset`, `context_checkpoint` | Human, summarizer | Context boundaries |
| `cwd_changed`, `member_added`, `member_removed`, `channel_changed` | Human | Channel changes |
| `delivery_cancelled` | Human | Cancelled pending deliveries |
| `system` | System | For example `max_hops` and `/cancel` notices |

## Migrations

`Store._migrate` adds missing columns with `ALTER TABLE`, normalizes old run errors and durations, assigns hues and avatars to agents that lack them, and builds `search_fts` once. There is no migration version table: every migration step checks whether its change already exists before applying it.

## Query helpers

- `scrollback`: pages of events with exclusive `before_seq` / `after_seq` cursors.
- `replay`: events after a global id, for the WebSocket.
- `channel_summary`: a channel's members, preview, unread count and active runs.
- `usage`: token totals by agent, channel or day.
- `search`: matches across channels, agents and messages.

## Related

- [Glossary](../overview/glossary.md) — seq, id, chain, hop.
- [Dispatch and queue](dispatch-and-queue.md) — how `dispatch_queue` rows move between states.
- [Live state](live-state.md) — the summaries built from these tables.
- [Attachments](attachments.md) — the attachments table in context.
