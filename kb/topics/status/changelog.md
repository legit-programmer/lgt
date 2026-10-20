---
id: 20261008-changelog
title: Changelog
tags: [status]
created: 2026-10-08
updated: 2026-10-21
related: [20261008-open-gaps, 20261008-mutable-channel-cwd, 20261008-conventions]
summary: Chronological record of what changed in the repo, by commit, so an agent can tell what is new and what superseded the original spec.
---

# Changelog

> Summary: Chronological record of what changed in the repo, by commit, so an agent can tell what is new and what superseded the original spec.

Add new entries at the top. Use `git log --oneline` for the full history.

## 2026-10-21

- Add the Artefacts tab with a 50/50 desktop view, Markdown rendering, sandboxed HTML, lazy PDF.js previews, rename/delete, live reopening on updates, historical Open buttons, and filesystem refresh. Bundle PDF assets for offline use.

- Add channel-scoped artefact folders, automatic setup and agent instructions, completed-message announcements, filesystem list/rename/delete/content APIs, and isolated HTML preview capabilities.

## 2026-10-18

- Remove the model router, random fallback, and generated starter suggestions. Require channel members and explicit primary selection before conversation; keep primary dispatch during overlapping tasks and preserve agent handoff/delegation. Separate checkpoint CLI settings from removed router settings.

## 2026-10-15

- Add README screenshots (`docs/screenshots/`): a dark and a light channel and the new-agent form, taken in headless Edge against a scratch backend with scripted custom-harness agents, so no model calls.
- Probe custom agents at startup and keep one unprobeable agent from breaking the WebSocket: after a restart, context stats for a custom agent raised `harness custom is not probed`, which aborted every connect, so agent cards showed no context or usage.
- Stop oversized Claude tool results from failing the run: a tool result over `ndjson_line_limit` (usually an image read inline as base64) becomes an "output omitted" result instead of `claude exited 1 (NDJSON line exceeds … bytes)`. Other oversized lines still fail.
- Rework the channel view after a UI critique: the conversation loses its pane box and sits on the window ground with a top fade and a hover-only scrollbar; Reply shows on hover; your messages take a faint fill instead of an outline; the top bar keeps only the primary pill, with a divider before the caption buttons; agent cards show now, last run, context and all-channel usage, with Remove in a ⋯ menu; Quit sits apart; the composer starts at one line; frosted surfaces collapse to a chrome and a pane level.
- Make the light frosted window readable over dark wallpapers: a heavier light Acrylic tint, a paper ground behind the shell, and more opaque light side panels.
- Add a frosted window on Windows: a transparent window with Acrylic, tinted side panels, and a **Frosted window** toggle in the channel menu and the command palette. Make the working label static and step the working dots, because their per-frame repaints, not the blur, cost the GPU.
- Support inline `<@agent_id:handoff>` and `<@agent_id:delegation>` in normal agent prose. Dispatch only after message completion, preserve task context and ownership checks, and render known targets as `@handle` in the desktop. Keep legacy transfers compatible and cover streaming, routing and rendering with tests.

## 2026-10-14

- Add a KB TODO note, starting with improving agent-to-agent delegation and handoff.
- Simplify the startup screen to a mark, title, caption and progress bar. Replace the native selects in the agent hover panel with model cards and a segmented reasoning meter, and show reasoning in the agent form as a segmented control.

## 2026-10-13

- Add harness-owned skill discovery for Codex and Claude, including scoped Claude plugins and legacy commands, native enabled state, source identity and partial discovery errors.
- Add channel/DM skill catalogs, explicit invocation APIs, primary defaults, eligible-agent selection, backend/new-agent actions, isolated turns and unchanged channel ownership.
- Check declared tool requirements and native Claude Skill access; retain unknown requirements and harness runtime enforcement. Normalize permission denials and expose explicit recovery actions. Revalidate queued installations and preserve transcripts through guarded backend switches.
- Cover discovery, provenance, routing, permissions, queue changes, native inputs, strict HTTP contracts and composer workflows with model-free tests.
- Verify 226 backend tests (excluding two existing POSIX process tests reproduced on unchanged HEAD), 49 desktop tests, the production build, and native Codex discovery without model calls.

## 2026-10-12

- Build the desktop app for Android and iOS as a paired-only client. Compile out the daemon launcher on mobile, split desktop and mobile capabilities, and commit the generated Android project and mobile icons.
- On a phone without a pairing, show **Pair with your workspace**, and scan the pairing QR with the camera; **Disconnect** replaces **Use local workspace**.
- Add the phone layout: sidebar drawer, panel sheet, compact top bar, safe areas, dynamic viewport height, 16px inputs, Android back-button handling, and touch-visible controls.
- On phone-width touch screens, swipe right for the sidebar and left for the channel panel, replacing both top bar toggles; panels slide in from their side.
- Replace `window.prompt` for host paths with an app dialog, and save attachments on mobile through the system picker (Android) or the app's Documents folder (iOS).
- Reuse the FastAPI gateway for authenticated remote clients, with configurable inbound listening and advertised pairing addresses.
- Persist named device credential hashes; local desktop administration creates, lists, renames and revokes connections. Revocation immediately closes device sockets and survives restarts.
- Add Settings → Devices with QR codes and verified pairing-code import into local storage. Paired clients skip local launch, use host filesystem paths, and quit without stopping the backend.
- Preserve loopback-only development and local-only launch tokens, device administration, and shutdown.
- Add whole-message and selected-text replies with backend quote previews, immutable text-only snapshots, a 4,000-character cap ending in `truncated..`, automatic author targeting, composer removal/draft retention and prompt context. Explicit reply mentions override the author; quoted mentions/tools never route work.

## 2026-10-11

- Persist one primary agent per channel. Follow-ups and new tasks stay with it after completion, without a router call. Explicit selections, accepted handoffs, and router assignments are the only ownership transitions.
- Route ambiguous messages through the router while independent tasks overlap; delegated work stays attributed to its parent. Version checks protect newer selections from delayed transfers and routing results.
- Add a shared agent transfer protocol, current roster/policy/assignment context, ownership and transfer history, and the channel header's primary/router indicator and automatic handoff toggle.
- Migrate existing databases additively, preserve ownership through restarts, and test routing, delegation, delayed acceptance, concurrency, shared-user state and frontend snapshots. Two pre-existing POSIX process tests also fail on unchanged HEAD in this container.

### Change agent model and reasoning from chat

- Add nullable persisted agent reasoning effort, per-model modes and defaults, a provider-preserving inference PATCH endpoint, and per-agent model catalogs.
- Send supported settings to Codex, Claude and custom harnesses. Existing null-effort fingerprints remain compatible; changed settings apply to the next run and trigger cold context rebuilding.
- Add a frosted transparent hover panel over agent identities with model selection, a stepped reasoning slider, keyboard access, and server-confirmed state. Unsupported controls display automatic reasoning.
- Validate catalog, migration, endpoint errors, busy-run snapshots and adapter arguments with focused backend tests; verify hover editing and server acknowledgment with focused desktop tests.


## 2026-10-10

- Use locally bundled Claude, Gemini and Codex logos throughout provider selection and metadata, with a theme-aware Codex mark and a terminal fallback for custom CLIs.
### Start the backend with the desktop

- The Tauri shell discovers or launches a persistent backend through owner-private `daemon.json`, with health identity and version checks and a per-launch token.
- HTTP, attachment fetches, and the initial WebSocket frame authenticate in daemon mode. Manual backend startup remains supported.
- Normal window close leaves runs active. **Quit Lgt** requests graceful shutdown. Daemon logs rotate under the workspace data directory.
- A frosted startup overlay shows **Setting up your Lgt workspace**, with an animated Lgt mark, reduced-motion support, and Retry on failure.
- Release packaging includes a real standalone Python runtime, pinned dependencies, and backend source.
- D1's startup and shutdown contract is implemented. Tray controls, notifications, start at login, and automatic restart after updates remain follow-up work.

## 2026-10-09

### Frosted composer, quieter messages, Critters avatars

- The composer floats over the timeline as frosted glass (12px blur), so scrolled messages show through it, blurred. The pane itself no longer has a backdrop filter.
- Your messages lose the amber fill and get a quiet hairline outline.
- Avatars:
  - The default DiceBear style is Critters (CC0).
  - The backend migrates existing default `bottts` avatars once (`PRAGMA user_version` 1).
  - The desktop moves to `@dicebear/core` 10 with lazily loaded `@dicebear/styles` definitions.

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
