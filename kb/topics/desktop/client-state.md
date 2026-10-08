---
id: 20261008-client-state
title: Client state and socket
tags: [desktop, api]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-websocket-protocol, 20261008-timeline-model, 20261008-http-actions-ws-state, 20261008-desktop-architecture]
summary: The Zustand workspace store (what it holds, how frames are applied, timeline paging), the socket's reconnect and resync logic, and the UI store with hash routing.
---

# Client state and socket

> Summary: The Zustand workspace store (what it holds, how frames are applied, timeline paging), the socket's reconnect and resync logic, and the UI store with hash routing.

## Workspace store (`desktop/src/store/workspace.ts`)

| Field | Source |
| --- | --- |
| `agents`, `channels`, `statuses`, `me` | `boot()` over HTTP, then the `agent`, `channel_summary`, `agent_status` and `me` frames |
| `timelines[channelId]` | `{events by seq, oldestSeq, hasOlder, loading}`. Filled by `loadTimeline` (latest 100), `loadOlder` (`before_seq`) and `loadAround(seq)`, then by `event` frames for loaded channels only. |
| `partials[runId]` | `delta` and `partial_snapshot` frames. Cleared by the run's `message` event or its terminal `run_status`. |
| `runs[runId]` | `run_status` events plus the `active_runs` of `agent_status`. Gives each run its agent, status and `started_at`. |
| `queues[channelId]`, `contexts["channel:agent"]`, `usage`, `limits` | The `queue`, `context`, `usage` and `harness_limits` frames |
| `lastEventId` | The highest event id seen, used as the reconnect cursor |
| `toasts` | Action failures and socket `error` frames |

`applyFrame` is the single reducer for socket frames, and `store/workspace.test.ts` tests it. A `resync` frame reloads summaries and force-reloads every open timeline.

## Socket (`desktop/src/store/socket.ts`)

- It sends `{last_id: lastEventId}` on open.
- It reconnects with exponential backoff, capped at 15 s, and refreshes summaries before each reconnect.
- The connection state moves through `connecting`, `open`, `reconnecting` and `unreachable`.
- `send()` exists, but every action goes over HTTP; see [the decision](../decisions/http-actions-ws-state.md).

## UI store (`desktop/src/store/ui.ts`)

- `view`: `home`, `channel` (with an optional `anchorSeq`), `agent-new`, `agent-edit` or `onboarding`. It is synced to the URL hash: `#/c/<id>`, `#/agents/new`, `#/agents/<id>`, `#/onboarding`.
- The detail panel tab, the run filter and the selected run; the palette and new-channel dialog flags.
- The theme, stored in `localStorage` as `lgt.theme`. It is a per-window display preference, not workspace state.

## Related

- [WebSocket protocol](../backend/websocket-protocol.md) — the frames being applied.
- [Timeline model](timeline-model.md) — how timelines become blocks.
- [HTTP for actions, WebSocket for state](../decisions/http-actions-ws-state.md) — why actions don't use the socket.
- [Desktop architecture](desktop-architecture.md) — boot sequence.
