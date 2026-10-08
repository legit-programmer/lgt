---
id: 20261008-changelog
title: Changelog
tags: [status]
created: 2026-10-08
updated: 2026-10-09
related: [20261008-open-gaps, 20261008-mutable-channel-cwd, 20261008-conventions]
summary: Chronological record of what changed in the repo, by commit, so an agent can tell what is new and what superseded the original spec.
---

# Changelog

> Summary: Chronological record of what changed in the repo, by commit, so an agent can tell what is new and what superseded the original spec.

Add new entries at the top. Use `git log --oneline` for the full history.

## 2026-10-09

### Top bar and black ground (desktop)

- On Windows the window is frameless (`tauri.windows.conf.json`).
- `components/TopBar.tsx` merges the title bar with the app chrome:
  - sidebar toggle, back/forward and the "new" menu on the left;
  - the view's title and actions, portaled from each screen, in the middle and on the right;
  - window controls at the far right.
- The in-pane conversation and agent-form headers are gone.
- The sidebar can collapse, and Alt+←/→ navigate the view history.
- The window ground is pitch black with no backdrop glows.

### Window glass tried and dropped (desktop)

- `8b592f5` made the window transparent with OS acrylic, so the side panels were frosted over the desktop.
- `b62515b` switched to a focus-only blur to cut the DWM GPU cost.
- The owner then dropped the effect, and both commits were reverted. The window is opaque again, with solid side panels as in the design.

## 2026-10-08

### Knowledge base

- Added `kb/` (this knowledge base), `AGENTS.md` and `CLAUDE.md`.

### `7396a2b`: profile and archive restore (desktop)

- The display name can be edited from the sidebar footer (`PATCH /me`).
- Archived channels can be restored from the palette.

### `75307e0`: desktop docs and new gaps

- Added `desktop/README.md`.
- `design/backend-gaps.md` gained the open section D1–D6.

### `92f74e5`: media over CORS and client tests

- Thumbnails and downloads load as blob URLs.
- Added vitest suites for the workspace store and formatting.

### `21481d3`: layout polish

- The view is synced to the URL hash.
- Paths truncate in the middle.
- The model picker gets its own row.

### `eec8f95`: desktop app scaffold

- Tauri v2 + React app in `desktop/`.
- Ember tokens and components.
- Typed client and WebSocket store.
- All five design screens, plus the palette.

### `8078244`: backend contracts for the desktop

- Claude, Gemini and custom adapters, plus harness discovery and catalogs.
- Enforced tool allowlists, `allowed_origins`, and agent identity (avatar, hue, extra args, auto-DM, retirement).
- Channel summaries with read cursors; agent status with activity.
- Enriched run payloads with structured errors; normalized tools; routing explanations.
- Context stats; token usage and plan limits, replacing `cost_usd`.
- FTS search, run logs, a command registry, and rename/unarchive.
- Templates and bootstrap, suggestions, the profile, and attachment quotas, retention and thumbnails.

### `9c974c5`: initial import

- The original Codex-only backend: store, orchestrator, router, context, gateway, process host, checkpoints.
- Also changing a channel's cwd (superseding the spec's immutable cwd), member removal, visible and cancellable queued deliveries, and attachments.

## Related

- [Open gaps](open-gaps.md) — what is still missing.
- [Mutable channel cwd](../decisions/mutable-channel-cwd.md) — the main spec override.
- [Conventions](../operations/conventions.md) — how to add entries.
