# Backend

The Python package in `lgt/`: storage, orchestration, harness adapters, and the HTTP and WebSocket gateway.

- [Runtime and configuration](runtime-and-config.md) — startup sequence, settings, data directory.
- [Event store](event-store.md) — schema, append-only log, event kinds, triggers, migrations, search.
- [Dispatch and queue](dispatch-and-queue.md) — mailboxes, queue states, coalescing, dispatch.
- [Run lifecycle](run-lifecycle.md) — statuses, output handling, cancellation, errors, orphan recovery.
- [Context and sessions](context-and-sessions.md) — prompt rendering, resume or cold, checkpoints.
- [Routing](routing.md) — model routing, reason codes, suggestions.
- [Harness adapters](harness-adapters.md) — registry, Codex, Claude, Gemini, custom.
- [Process hosting](process-hosting.md) — process trees, Job Objects, SDK host, one-shot calls.
- [Attachments](attachments.md) — storage, limits, binding, serving, native inputs.
- [Gateway HTTP API](gateway-http.md) — origin policy, errors, route map.
- [WebSocket protocol](websocket-protocol.md) — handshake, frames, overflow.
- [Live state frames](live-state.md) — summaries, statuses, context, usage, limits.
