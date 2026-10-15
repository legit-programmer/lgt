---
id: 20261008-live-state
title: Live state frames
tags: [backend, api]
created: 2026-10-08
updated: 2026-10-15
related: [20261008-websocket-protocol, 20261008-event-store, 20261008-screens, 20261008-context-and-sessions]
summary: The server-computed state behind the sidebar, status dots, activity lines, context header and usage — channel summaries, agent statuses, context stats, usage totals, plan limits, profile — and when each is published.
---

# Live state frames

> Summary: The server-computed state behind the sidebar, status dots, activity lines, context header and usage — channel summaries, agent statuses, context stats, usage totals, plan limits, profile — and when each is published.

The UI shows these objects as they are. Each one has an HTTP route for the first load and a WebSocket frame for changes. `Orchestrator.snapshot_frames` builds the initial set.

Context frames go through `_context_frames`, which skips (and logs) an agent whose `context_stats` raises `WorkspaceError`, such as a custom agent whose command no longer probes. One such agent used to abort the WebSocket handshake, so the client reconnected in a loop and never received any state frames.

| Object | HTTP | Built by | Published when |
| --- | --- | --- | --- |
| Channel summary: `members`, `last_activity_at`, `preview {seq, kind, author_id, text_excerpt}`, `unread_count`, `active_runs`, `primary_agent_id`, `ownership_version`, `allow_handoff`, `routing_mode`, `active_task_agent_ids` | `GET /channels` | `Store.channel_summary` and `routing_state` | Any event in the channel (`_publish_summary`), or a read-cursor change |
| Agent status: `state` (`idle`, `working`, `queued` or `failed`), `active_runs`, `activity {kind, summary, since}`, `last_failure` | `GET /agents/status` | `Orchestrator.agent_statuses` | After every publish, when changed (`_publish_agent_statuses`) |
| Context: `mode`, `start_seq`, `messages_in_context`, `context_tokens`, `model_context_window`, `checkpoint_seq` | `GET /channels/{id}/context?agent_id=` | `Orchestrator.context_stats` | Usage updates, resets, checkpoints, cwd changes, edits |
| Usage totals by agent | `GET /usage` | `Store.usage` | Every usage update |
| Plan limits | `GET /harnesses/{h}/limits` | `Store.get_harness_limits` | A harness `limits` event (Codex rate-limit windows) |
| Profile | `GET /me` | `Store.get_human_profile` | `PATCH /me` |

## Rules

- **Read cursors are server state** (`POST /channels/{id}/read {seq}`). They advance monotonically and survive restarts. Unread counts include agent messages after the cursor.
- **Previews follow edits**, and deletions hide the original text.
- **No currency:** `cost_usd` is never returned. Usage means token counters and the harness's own plan-limit windows.
- **Ownership is channel-wide:** the desktop uses the server's `routing_mode` and stored primary. It never guesses the next recipient from completion order or the last speaker. Delegated task activity is attributed to its parent; independent overlap temporarily uses the router.

## Related

- [WebSocket protocol](websocket-protocol.md) — frame delivery and order.
- [Event store](event-store.md) — the queries behind summaries and usage.
- [Screens](../desktop/screens.md) — where each object is displayed.
- [Context and sessions](context-and-sessions.md) — how context stats are derived.
