---
id: 20261008-attachments
title: Attachments
tags: [backend, attachments]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-event-store, 20261008-origins-and-media, 20261008-context-and-sessions, 20261008-gateway-http]
summary: Upload storage outside channel directories, size and quota limits, retention of unsent files, binding to exactly one message, thumbnails, and how files reach each harness.
---

# Attachments

> Summary: Upload storage outside channel directories, size and quota limits, retention of unsent files, binding to exactly one message, thumbnails, and how files reach each harness.

## Flow

1. **Upload:** `POST /channels/{id}/attachments?filename=…` sends the raw body, with `Content-Type` as the media type. `Orchestrator.create_attachment` streams it to `data_dir/attachments/<attachment_id>/<safe_filename>` through `attachments.write_stream`, which computes SHA-256 and enforces `attachment_max_bytes` (`413 too_large`, leaving no partial file).
   - The channel quota `attachment_channel_quota_bytes` counts sent and unsent files, including concurrent uploads.
2. **Send:** `POST /channels/{id}/messages` with `attachments: [ids]`. Each attachment must belong to the channel and be unsent. The message payload records `{attachment_id, filename, media_type, size_bytes}`, and `bind_attachment` sets `message_seq`. SQL triggers then make it immutable.
3. **Discard:** `DELETE /attachments/{id}` works only on unsent attachments. Unsent uploads older than `attachment_retention_seconds` are removed at startup and periodically (`_retain_attachments`).

## Serving

| Route | Behavior |
| --- | --- |
| `GET /attachments/{id}` | PNG, JPEG, GIF and WebP are served inline. Everything else is served as `application/octet-stream` with `Content-Disposition: attachment`, `nosniff` and `CSP: sandbox`, so uploaded HTML or SVG never runs in the app origin. |
| `GET /attachments/{id}/thumbnail` | A Pillow JPEG bounded by `thumbnail_max_dimension`. Decompression bombs are rejected. |
| `GET /attachments/{id}/meta` | Metadata, including `message_seq` and the download `url`. |

The desktop app loads these through CORS fetches and blob URLs; see [origins and media](../desktop/origins-and-media.md).

## Reaching agents

- Every agent sees file names and absolute paths in its rendered prompt ([context](context-and-sessions.md)).
- `Turn.attachments` carries the files of the messages that triggered the run.
  - Codex receives images as `localImage` inputs.
  - Claude receives images and PDFs as native content blocks.
  - Custom harnesses receive paths and metadata in their turn request.

## Files

`lgt/attachments.py` contains `safe_filename`, `normalize_media_type`, `write_stream`, `AttachmentTooLarge` and `VIEWABLE_IMAGE_TYPES`. The orchestrator methods `create_attachment`, `delete_attachment` and `cleanup_attachments`, and the attachment routes in `lgt/gateway.py`, use them.

## Related

- [Event store](event-store.md) — the attachments table and triggers.
- [Origins and media](../desktop/origins-and-media.md) — how the UI fetches files.
- [Context and sessions](context-and-sessions.md) — attachment lines in prompts.
- [Gateway HTTP](gateway-http.md) — the routes.
