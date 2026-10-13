# Backend

The Python package in `lgt/`: storage, orchestration, harness adapters, and the HTTP and WebSocket gateway.

- [Runtime and configuration](runtime-and-config.md) — startup sequence, settings, data directory.
- [Event store](event-store.md) — schema, append-only log, event kinds, triggers, migrations, search.
- [Dispatch and queue](dispatch-and-queue.md) — mailboxes, queue states, coalescing, dispatch.
- [Run lifecycle](run-lifecycle.md) — statuses, output handling, cancellation, errors, orphan recovery.
- [Context and sessions](context-and-sessions.md) — prompt rendering, resume or cold, checkpoints.
- [Message replies](message-replies.md) — text-only quotes, selected text, author routing and composer drafts.
- [Routing](routing.md) — shared ownership, handoff/delegation, direct follow-ups, overlapping tasks, model routing and suggestions.
- [Harness adapters](harness-adapters.md) — registry, model reasoning modes, Codex, Claude, Gemini, custom.
- [Skill discovery and invocation](skill-invocation.md) — sources, executor selection, native loading and permission gates.
- [Process hosting](process-hosting.md) — process trees, Job Objects, SDK host, one-shot calls.
- [Attachments](attachments.md) — storage, limits, binding, serving, native inputs.
- [Gateway HTTP API](gateway-http.md) — origin policy, errors, route map.
- [Device pairing and remote access](device-pairing.md) — named credentials, QR payloads, listener configuration, and local revocation.
- [WebSocket protocol](websocket-protocol.md) — handshake, frames, overflow.
- [Live state frames](live-state.md) — summaries, statuses, context, usage, limits.

- [Desktop daemon lifecycle](desktop-daemon.md) - discovery, detached launch, authentication, shutdown.
