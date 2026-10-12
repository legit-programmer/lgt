---
id: 20261012-message-replies
title: Message replies
tags: [backend, desktop, api, routing, context, ui]
created: 2026-10-12
updated: 2026-10-12
related: [20261008-context-and-sessions, 20261008-gateway-http, 20261008-timeline-model, 20261008-routing]
summary: Whole-message and selected-text reply quotes, automatic author routing, snapshots, truncation, and composer drafts.
---

# Message replies

`lgt/replies.py` builds text-only snapshots from channel-scoped message events. The server applies existing edits and rejects deleted/non-message sources. Whole-message replies quote `payload.text`; selection replies accept nonempty visible text from the desktop, since rendered Markdown differs from its source. The quote includes source sequence, author identity/handle, text, `selected` and `truncated`. It omits attachments, tools and nested reply metadata.

The maximum is 4,000 Unicode characters including `\ntruncated..` when shortened. This approximates 1,000 English tokens, rather than enforcing a tokenizer-specific token budget. Selection replies help reference the middle of long messages.

`Orchestrator.preview_reply` and `POST /channels/{id}/reply-preview` provide the bounded quote for the composer. `send_message` accepts `reply_to_seq` and optional `reply_selection`, resolves the source again inside its mailbox and stores `payload.reply` separately from the new `payload.text`. Sent snapshots survive later source edits/deletions. A reply needs new text or an attachment, just like an ordinary message. Slash-command text in replies is sent to the agent as text.

An agent reply targets its author and selects it as primary. Explicit recipients/known mentions in the actual reply override that target; quoted mentions have no effect. Human-message replies follow ordinary routing. Removed/retired source agents cause an error without appending a message. The composer retains a failed draft.

`context.render_delta` labels and serializes the quote before the actual reply in cold/resumed turns. `render_turn` includes it in channel `assigned_messages`. The quote remains useful when the source is outside the delta, checkpoint tail, or reset boundary.

`blocks.tsx` gives every committed message a Reply action. Its selection action accepts a range only inside one `.fv-message-text` body, excluding tool rows, attachments and nested quote displays. `ChannelScreen` requests the backend preview and guards stale preview responses. `Composer` shows the quote, allows removal/Escape, sends the reference and selected text, and clears on success. In-window drafts retain their reply when switching channels. Partial streaming text is not replyable until committed as a message event.

Tests: `tests/test_orchestrator.py`, `tests/test_gateway.py`, and `desktop/src/features/channel/Reply.test.tsx` cover routing, snapshots, invalid targets, context, truncation, rendered Markdown selection, tool/multiple-message exclusion, and draft retention.

## Related

- [Context and sessions](context-and-sessions.md) — how reply reference context reaches the harness.
- [Gateway HTTP API](gateway-http.md) — source validation and preview/send contracts.
- [Timeline model](../desktop/timeline-model.md) — message events and run segments behind reply actions.
- [Routing](routing.md) — author selection updates channel ownership.
