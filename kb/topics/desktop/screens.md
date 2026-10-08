---
id: 20261008-screens
title: Screens and features
tags: [desktop, ui]
created: 2026-10-08
updated: 2026-10-09
related: [20261008-timeline-model, 20261008-live-state, 20261008-design-system, 20261008-open-gaps]
summary: Which desktop/src/features file implements each screen of Lgt Screens.pdf, which backend routes each uses, and which design elements are deliberately omitted.
---

# Screens and features

> Summary: Which desktop/src/features file implements each screen of Lgt Screens.pdf, which backend routes each uses, and which design elements are deliberately omitted.

## Map

| Design screen | Files | Backend |
| --- | --- | --- |
| Sidebar: DMs, channels, footer | `features/sidebar/Sidebar.tsx`, `ProfileDialog.tsx` | Channel summaries, agent statuses, `PATCH /me` |
| 1. Channel view and detail panel | `features/channel/ChannelScreen.tsx` (headers, cwd menu), `Timeline.tsx`, `blocks.tsx`, `Composer.tsx`, `DetailPanel.tsx` (Agents and Run tabs), `RenameDialog.tsx` | Events, messages, members, cwd, queue, cancel delivery, runs, run logs, limits, rename, archive |
| 2. DM view | `ChannelScreen.tsx` (`DmHeader`) | `context` frames (messages in context, tokens), `/new` |
| 3. New or edit agent | `features/agents/AgentForm.tsx` | `/harnesses`, `/harnesses/scan`, `/harnesses/custom/probe`, `POST /agents`, `PUT /agents/{id}`, `/agents/{id}/retire` |
| 4. Empty channel | `features/channel/EmptyChannel.tsx` | `/channels/{id}/suggestions`, `/cwd` |
| 5. Onboarding | `features/onboarding/Onboarding.tsx` | `/harnesses`, `/templates`, `/bootstrap` |
| New channel | `features/channel/NewChannelDialog.tsx` | `POST /channels` |
| Ctrl/⌘ K palette | `features/palette/CommandPalette.tsx` | `/search`, `/unarchive` |

## Top bar

`components/TopBar.tsx` holds the sidebar toggle, back/forward and the "new" menu. Each screen portals its header into it through `TopBarSlot`:
- **Channel:** `#name`, working count, cwd menu; search, panel toggle, more.
- **DM:** avatar, handle, status, CLI and model, cwd, context stats; Fresh context, search, edit.
- **Agent form:** "New agent" or "Edit …"; Retire.

## Composer (`Composer.tsx`)

- **Mentions and commands:** `@` autocompletes channel members (not shown in DMs), and `/` lists `GET /commands`; commands run on the server.
- **Attachments:** files upload as soon as they're picked, pasted or dropped, and appear as removable chips. Removing a chip deletes the unsent upload.
- **Drafts:** kept in memory per channel.
- **Keys:** Enter sends, and Shift+Enter adds a newline.

## Deliberately omitted

- Voice input (the mic button): WebView2 has no built-in speech recognition. This is frontend work, not a backend gap.
- The × that cancels a single live tool call: no backend endpoint (D6).
- Per-tool durations from Claude (D3), and "cancelled by you" wording (D5).
- Tray icon, notifications and start at login: these need the daemon handshake (D1).

See [open gaps](../status/open-gaps.md).

## Related

- [Timeline model](timeline-model.md) — the conversation rendering rules.
- [Live state](../backend/live-state.md) — the data each screen shows.
- [Design system](design-system.md) — the visual language.
- [Open gaps](../status/open-gaps.md) — why some elements are missing.
