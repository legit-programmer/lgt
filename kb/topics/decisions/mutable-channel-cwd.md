---
id: 20261008-mutable-channel-cwd
title: "Decision: channel working directory can change"
tags: [decision, backend, context]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-context-and-sessions, 20261008-event-store, 20261008-changelog]
summary: Why the original spec's immutable channel cwd was replaced by a guarded change that forces cold rebuilds, and the rules of PUT /channels/{id}/cwd.
---

# Decision: channel working directory can change

> Summary: Why the original spec's immutable channel cwd was replaced by a guarded change that forces cold rebuilds, and the rules of PUT /channels/{id}/cwd.

## Context

The original spec made a channel's cwd immutable, because Claude Code namespaces sessions by directory and a change would orphan them. The design's empty-channel screen has a **Change working directory** button.

## Decision

- `PUT /channels/{id}/cwd` takes an existing absolute directory, or `null` for the managed directory. It is implemented in `Orchestrator.set_channel_cwd`.
- The change is refused while any run in the channel is active, because runs capture the cwd at dispatch.
- It appends a `cwd_changed` event with `cwd`, `previous_cwd` and `managed`. The `channels_cwd_immutable` trigger is dropped in `schema.sql`.
- Sessions check `session.cwd == channel.cwd`, so every agent rebuilds cold from the log, and the rendered prompt states the new directory. The old directory stays on disk.
- `/cwd <path>` in the composer does the same.

## Consequences

- No session is ever resumed in the wrong directory, and no history is lost.
- The next turn after a change costs a cold rebuild.

## Related

- [Context and sessions](../backend/context-and-sessions.md) — session validity rules.
- [Event store](../backend/event-store.md) — the dropped trigger.
- [Changelog](../status/changelog.md) — when this changed.
