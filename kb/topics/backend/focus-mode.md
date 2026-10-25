---
id: 20261025-focus-mode
title: Focus mode
tags: [backend, desktop, context, runs, ui]
created: 2026-10-25
updated: 2026-10-25
related: [20261008-context-and-sessions, 20261008-run-lifecycle, 20261008-harness-adapters, 20261008-screens, 20261008-timeline-model, 20261008-event-store, 20261021-artefacts]
summary: Per-channel and DM Focus controls determine streaming, retained history, final-reply selection and native session reuse.
---

# Focus mode

`Channel.focus_mode` defaults to false for new channels, DMs and migrated databases. `PATCH /channels/{id}` accepts `focus_mode`; the mailbox saves it, appends `channel_changed`, and publishes authoritative channel summaries and context. Running turns keep their captured `Turn.channel` settings. A toggle affects the next dispatched turn.

## Storage and delivery

- **On:** existing full streaming. `_output` publishes text deltas and `_append_output` commits all completed messages and raw tool calls/results, with normal transfer handling.
- **Off:** `_output` drops deltas and raw tools before storage/publication, retains tool counts, and holds only the latest possible final reply in memory. Tool activity invalidates earlier candidate replies. Explicit commentary cannot become a final reply. Only successful termination commits the final message through `_append_output`; questions and transfers are ordinary final replies. Failed/cancelled turns discard pending text. `_finish` writes a `tool_summary` when tools ran, including on failure/cancellation.
- `tool_summary` stores `author_handle`, `tools` (name → count) and `total`, with the agent author and run ID. No arguments or results are stored. `render_delta` renders the same condensed tool line as full-history runs; checkpoint sizing includes it.
- Activity for quiet turns is generic `working` / `Working`. Usage, queue, run status and failure notices remain live. There are no quiet partial snapshots to recover on reconnect.
- Existing Focus-on history is preserved. Turning Focus on cannot recover discarded quiet activity.

## Final replies and context

Codex forwards its message `phase` (`commentary` or `final_answer`). Claude supplies terminal `result` text as normalized `run_finished.final_message`. Gemini supplies text from after its last tool activity. Custom messages can optionally declare a phase; legacy messages use the last completed message after the final tool activity. Authoritative terminal text supersedes any candidate reply, including an empty terminal reply. Streaming adapters wait for a successful process exit before reporting completion.

Quiet turns always rebuild cold from the retained channel log and valid checkpoint. Successful quiet sessions are saved dirty and cannot be resumed after switching back on. Native session validation also rejects focus-setting changes since the previous turn. This prevents CLI-internal intermediate text and raw tools from reentering later context. Native CLIs may keep their own diagnostic/session artifacts; LGT does not reuse that history for quiet turns. A prompt `<response_mode>` asks for autonomous work, final results or necessary questions, with no progress narration.

## Client

`features/channel/FocusModeToggle.tsx` appears in both channel and DM headers. It patches the setting and displays the server's saved value. `buildTimeline` places `tool_summary` on its run block; `RunSegment` renders names/counts without expandable tool rows. The UI performs no filtering to implement quiet mode.

## Verification

`tests/test_focus_mode.py` covers live suppression, replay/search/snapshots, future same-agent and new-agent context, final questions, failure/cancellation, transfers, mode changes during runs, session reuse and per-conversation persistence. Adapter tests cover phase and final-text selection; route tests cover HTTP/WebSocket state and migration tests preserve existing log events. Desktop tests cover authoritative toggles and summary rendering.

## Related

- [Context and sessions](context-and-sessions.md) — rendering, checkpoints and native session validation.
- [Run lifecycle](run-lifecycle.md) — normalized output and termination.
- [Harness adapters](harness-adapters.md) — provider protocols and final replies.
- [Screens](../desktop/screens.md) — header controls.
- [Timeline model](../desktop/timeline-model.md) — run blocks and tool summaries.
- [Event store](event-store.md) — persisted channel preference and append-only history.
- [Channel artefacts](artefacts.md) — final artefact announcements in quiet turns.
