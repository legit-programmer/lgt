---
id: 20261008-context-and-sessions
title: Context and sessions
tags: [backend, context]
created: 2026-10-08
updated: 2026-10-12
related: [20261008-run-lifecycle, 20261008-mutable-channel-cwd, 20261008-glossary, 20261008-live-state, 20261012-message-replies]
summary: How a turn's prompt is rendered from the log, when a harness session is resumed versus rebuilt cold, how resets and edits invalidate sessions, and how checkpoints summarize old context.
---

# Context and sessions

> Summary: How a turn's prompt is rendered from the log, when a harness session is resumed versus rebuilt cold, how resets and edits invalidate sessions, and how checkpoints summarize old context.

## Rendering (`lgt/context.py`)

`render_delta(store, agent_id, channel_id, from_seq, to_seq, mode)` produces this shape:

```
<channel name="…" new_since="N">
[author] text
  (attached file.png, image/png, 1234 bytes, at C:/…/attachments/…/file.png)
[coder] (ran 3 tools: bash, edit x2)
[system] The channel working directory is now …
</channel>
```

- Edits are applied as of `to_seq`. Deleted messages are skipped.
- Replies carry a text-only, bounded snapshot as labeled reference context before the actual reply, even when the source is outside this delta. Channel `assigned_messages` includes the same quote metadata.
- Tool calls collapse to one line per run, and raw tool output is never rendered.
- In `resume` mode, the agent's own messages and tools are omitted, because its session already has them.
- `cwd_changed`, `member_added`, `member_removed` and `system` events render as `[system]` lines.
- Attachment paths are resolved at render time, so the log never stores data-directory paths.
- `render_turn` prepends `<context_checkpoint>` summary text when the plan uses a checkpoint.
- Channel turns also prepend `<channel_routing>` with current primary, handoff policy, member handles/IDs/descriptions, and `assigned_messages` for the delivered queue batch. Assigned text respects edits, deletion and context-reset boundaries. This block refreshes on resumed turns as well as cold ones; DMs retain their original prompt shape.
- Ownership and transfer events render as system history. Ownership notices save the selected handle so later renaming cannot change historical prompts. Transfer envelopes are explicit messages; ordinary agent mentions delegate.

## Resume or cold (`resolve_session`)

A stored session resumes only if all of these hold:

- `last_run_status` is `clean`;
- the harness is unchanged;
- the agent config fingerprint (harness, model, explicit reasoning effort, system prompt, tools, permissions and argv) is unchanged;
- the session cwd equals the channel's cwd;
- `last_seen_seq <= end_seq`;
- the harness artifact still exists (`artifact_exists`, for example Codex's rollout file under `CODEX_HOME/sessions`);
- the session is within `session_ttl_seconds`, when one is set;
- no `context_reset` happened, and no edit touched a seq the session had already seen.

Otherwise `cold_plan` starts from the newest valid checkpoint, or from the event after the last reset. Custom harnesses (protocol v1) always run cold.

## Checkpoints

- Every rendered append updates `channels.rendered_chars_since_checkpoint`.
- After a completed run, when the counter passes `checkpoint_threshold`, `_maybe_checkpoint` keeps a tail of about `checkpoint_tail_chars` and asks the summarizer to compress the rest into at most `checkpoint_summary_chars`.
- `CLISummarizer` (`lgt/summarizer.py`) uses Claude, then the Codex fallback, with the router model.
- The result is appended as `context_checkpoint` with `covers_through_seq`, unless a reset or an edit inside the covered range happened while it was being generated.
- Checkpoints only run when `checkpoint_mode` is `cli`.

## Context stats

`Orchestrator.context_stats` reports, for one agent and channel:
- `mode` and `start_seq`;
- `messages_in_context`;
- `context_tokens` and `model_context_window`, from the latest run in the current context;
- `checkpoint_seq`.

A reset, a cwd change or an earlier edit makes the usage numbers unknown (null). They are pushed as `context` frames.

## Related

- [Message replies](message-replies.md) — source snapshots, selection and truncation.

- [Run lifecycle](run-lifecycle.md) — where sessions are marked clean or dirty.
- [Mutable channel cwd](../decisions/mutable-channel-cwd.md) — why a cwd change forces cold rebuilds.
- [Glossary](../overview/glossary.md) — resume, cold, checkpoint.
- [Live state](live-state.md) — the `context` frame.
