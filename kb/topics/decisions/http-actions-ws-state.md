---
id: 20261008-http-actions-ws-state
title: "Decision: HTTP for actions, WebSocket for state"
tags: [decision, desktop, api]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-client-state, 20261008-websocket-protocol, 20261008-gateway-http]
summary: Why the desktop sends every mutation over HTTP and uses the WebSocket only to receive events, deltas and state frames.
---

# Decision: HTTP for actions, WebSocket for state

> Summary: Why the desktop sends every mutation over HTTP and uses the WebSocket only to receive events, deltas and state frames.

## Context

The backend accepts some commands over both transports: `send_message`, `edit_message`, `cancel_run`, `new_context` and `cancel_delivery`. A WebSocket `error` frame carries no correlation id, so a client can't tell which command failed.

## Decision

- Every action uses HTTP (`desktop/src/api/client.ts`). A failure maps to the `ApiError` of the action that caused it, which the UI shows as a toast or an inline form error.
- The socket is receive-only in practice. `WorkspaceSocket.send` exists, but nothing uses it.
- HTTP responses aren't applied as optimistic state. The resulting events arrive over the socket, so the log stays the single source.

## Consequences

- Error handling is per action and simple.
- The UI updates when the server's event arrives, typically within milliseconds on loopback.

## Related

- [Client state](../desktop/client-state.md) — the receiving side.
- [WebSocket protocol](../backend/websocket-protocol.md) — frames and commands.
- [Gateway HTTP](../backend/gateway-http.md) — the error envelope.
