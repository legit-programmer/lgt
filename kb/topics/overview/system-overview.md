---
id: 20261008-system-overview
title: System overview
tags: [overview]
created: 2026-10-08
updated: 2026-10-18
related: [20261008-repo-map, 20261008-glossary, 20261008-desktop-architecture, 20261008-dispatch-and-queue, 20261008-no-frontend-workarounds, 20261008-event-store, 20261008-context-and-sessions, 20261008-gateway-http, 20261012-device-pairing]
summary: What Lgt is, its two halves (Python backend and Tauri desktop app), and how a message flows from the composer to an agent and back.
---

# System overview

> Summary: What Lgt is, its two halves (Python backend and Tauri desktop app), and how a message flows from the composer to an agent and back.

## Context

Lgt is a local, single-user workspace where one person talks to a team of AI coding agents. Each agent is a configuration that runs a coding CLI already installed on the machine: Codex, Claude Code, Gemini, or a custom stdio command. Agents work in DMs (one agent) and channels (several agents). Channels require members and an explicitly selected primary. Unmentioned messages use that primary even during independent overlapping work.

## Details

### The two halves

| Half | Location | Stack | Role |
| --- | --- | --- | --- |
| Backend | `lgt/` | Python 3.13, FastAPI, Uvicorn, SQLite | Owns all state, runs agents as subprocesses, and serves HTTP and WebSocket on a configured listener (loopback by default) |
| Desktop app | `desktop/` | Tauri v2 (Rust), React 19, TypeScript, Vite | Renders the Ember screens, sends actions over HTTP, and receives live state over WebSocket |

The backend is the source of truth. The desktop app derives nothing on its own; see [no frontend workarounds](../decisions/no-frontend-workarounds.md).

### Message flow

1. The composer sends `POST /channels/{id}/messages` (`desktop/src/features/channel/Composer.tsx`).
2. `Orchestrator.send_message` (`lgt/orchestrator.py`) appends an immutable `message` event and enqueues deliveries:
   - in a DM, to its single agent;
   - with mentions, to each mentioned agent, plus a `routing_decision` event with `method: "mention"`;
   - without mentions, directly to the eligible channel primary. Channels without a valid primary reject sends before appending a message.
3. The channel's mailbox pumps the queue. Each idle agent gets a `Run`, and its turn prompt is rendered from the log (`lgt/context.py`).
4. A harness adapter starts the CLI and turns its output into normalized events: text deltas, tool calls and results, messages, usage, and the terminal event.
5. Each event is appended to the log and published on the event bus. The WebSocket gateway forwards it to the desktop, together with state frames (channel summaries, agent status, context, usage).
6. The desktop store applies the frames, and `buildTimeline` turns the log into run blocks, tool groups and notices (`desktop/src/lib/timeline.ts`).

### Key properties

- **Append-only log:** an edit is a new `message_edit` event; nothing is updated in place ([event store](../backend/event-store.md)).
- **One run per agent per channel:** messages that arrive while the agent is busy queue up and coalesce into its next turn ([dispatch](../backend/dispatch-and-queue.md)).
- **Session resume when valid, otherwise a cold rebuild from the log** ([context and sessions](../backend/context-and-sessions.md)).
- **Local or paired access:** loopback by default; remote listeners require persistent device credentials and an origin allowlist. Administration stays local ([pairing](../backend/device-pairing.md)).

## Related

- [Repo map](repo-map.md) — next step: where each piece lives.
- [Glossary](glossary.md) — prerequisite: terms used throughout the KB.
- [Desktop architecture](../desktop/desktop-architecture.md) — the client half in detail.
- [Dispatch and queue](../backend/dispatch-and-queue.md) — the core backend loop.

- [Device pairing and remote access](../backend/device-pairing.md) — persistent credentials and local device administration.
