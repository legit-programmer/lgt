---
id: 20261008-websocket-protocol
title: WebSocket protocol
tags: [backend, api]
created: 2026-10-08
updated: 2026-10-10
related: [20261008-live-state, 20261008-client-state, 20261008-gateway-http, 20261008-open-gaps, 20261010-desktop-daemon]
summary: The /ws cursor handshake, replay and snapshot order, every server frame type, client commands, and overflow/resync behavior of the event bus.
---

# WebSocket protocol

> Summary: The /ws cursor handshake, replay and snapshot order, every server frame type, client commands, and overflow/resync behavior of the event bus.

## Handshake and order (`gateway.websocket_endpoint`)

1. The client sends `{"last_id": n}` first in manual mode. Daemon mode requires `{"last_id": n, "token": "<launch-token>"}` within five seconds. Missing or invalid credentials close the socket with 1008 before any workspace data is sent. Anything else gets an `invalid_cursor` error and a 1008 close.
2. The server subscribes to the bus for every channel the human belongs to (`broadcast.EventBus`). Then it captures replay rows, partial snapshots, queue snapshots and state frames.
3. It sends the replayed `event` frames with id greater than `last_id`. If there are more than `replay_cap`, it sends one `resync` frame instead.
4. It sends `partial_snapshot` for each run that is streaming, `queue` for each channel with pending deliveries, then the state frames: `channel_summary`, `agent_status`, `context`, `usage`, `harness_limits` and `me` ([live state](live-state.md)).
5. It streams live frames. Durable events already sent in the replay are de-duplicated by id.

## Server frames

| Frame | Payload | Durable |
| --- | --- | --- |
| `event` | `{event: {id, channel_id, seq, ts, kind, author_kind, author_id, run_id, chain_id, hop, payload}}` | yes |
| `delta` | `{run_id, channel_id, text}`: live text | no |
| `partial_snapshot` | `{run_id, channel_id, text}`: catch-up for a streaming run | no |
| `queue` | `{channel_id, items: [{queue_id, event_seq, agent_id, state, created_at}]}`: the full pending list | no |
| `channel_summary`, `agent_status`, `context`, `me` | The HTTP object, flattened beside `type` | no |
| `usage` | A run's counters plus agent `totals` | no |
| `harness_limits` | `{harness, limits}` | no |
| `agent` | The full agent, flattened: created, changed or retired | no |
| `resync` | `{channels}`: reload these over HTTP | — |
| `error` | `{error: {code, message}}`: a failed command | — |

## Client commands

These are optional; the desktop app uses HTTP for actions instead.

`send_message`, `edit_message`, `cancel_run`, `new_context` and `cancel_delivery`, each with a `type` field. Errors come back as `error` frames with no correlation id.

## Overflow

Each subscription has a queue of `replay_cap` frames. A slow client that overflows gets a `resync` frame, and the socket closes with code 1013. The client then reconnects from its cursor.

## Known gap

There is no way to start from "now". The first connection sends `last_id: 0` and replays history; see D2 in [open gaps](../status/open-gaps.md).

## Related

- [Live state](live-state.md) — what the state frames contain.
- [Client state](../desktop/client-state.md) — how the desktop applies frames.
- [Gateway HTTP](gateway-http.md) — the origin policy also guards `/ws`.
- [Open gaps](../status/open-gaps.md) — head cursor (D2).

- [Desktop daemon](desktop-daemon.md) - discovery, launch tokens, and shutdown.
