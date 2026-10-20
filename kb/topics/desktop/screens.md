---
id: 20261008-screens
title: Screens and features
tags: [desktop, ui]
created: 2026-10-08
updated: 2026-10-21
related: [20261008-timeline-model, 20261008-live-state, 20261008-design-system, 20261008-open-gaps, 20261013-skill-invocation, 20261021-artefacts]
summary: Which desktop/src/features file implements each screen of Lgt Screens.pdf, which backend routes each uses, and which design elements are deliberately omitted.
---

# Screens and features

> Summary: Which desktop/src/features file implements each screen of Lgt Screens.pdf, which backend routes each uses, and which design elements are deliberately omitted.

## Map

The composer lists skills across Codex and Claude installations through `/` and `/list`. Server-provided eligibility drives default execution and `SkillDialog.tsx` choices. `SkillRecovery.tsx` exposes explicit retry/settings actions after permission failures. Agent forms support a requested backend and creating an agent directly for a channel. See [Skill discovery and invocation](../backend/skill-invocation.md).

| Design screen | Files | Backend |
| --- | --- | --- |
| Sidebar: DMs, channels, footer | `features/sidebar/Sidebar.tsx`, `ProfileDialog.tsx` | Channel summaries, agent statuses, `PATCH /me` |
| 1. Channel view and detail panel | `features/channel/ChannelScreen.tsx` (headers, cwd menu, primary indicator and handoff toggle), `Timeline.tsx`, `blocks.tsx`, `Composer.tsx`, `DetailPanel.tsx` (Agents and Run tabs), `RenameDialog.tsx` | Events, messages, members, cwd, queue, cancel delivery, runs, run logs, limits, rename, archive, server-computed routing state and `allow_handoff` channel patch |
| 2. DM view | `ChannelScreen.tsx` (`DmHeader`) | `context` frames (messages in context, tokens), `/new` |
| 3. New or edit agent | `features/agents/AgentForm.tsx` | `/harnesses`, `/harnesses/scan`, `/harnesses/custom/probe`, `POST /agents`, `PUT /agents/{id}`, `/agents/{id}/retire` |
| 4. Empty channel | `features/channel/EmptyChannel.tsx` | `/cwd` and channel membership/primary state |
| 5. Onboarding | `features/onboarding/Onboarding.tsx` | `/harnesses`, `/templates`, `/bootstrap` |
| New channel | `features/channel/NewChannelDialog.tsx` | `POST /channels` with nonempty members and explicit `primary_agent_id` |
| Ctrl/⌘ K palette | `features/palette/CommandPalette.tsx` | `/search`, `/unarchive` |

## Top bar

`components/TopBar.tsx` holds the sidebar toggle, back/forward and the "new" menu. Each screen portals its header into it through `TopBarSlot`:
- **Channel:** `#name`, working count and cwd menu as plain grey text, the primary pill; search, panel toggle, more, then a divider before the caption buttons.
- **DM:** avatar, handle, status, CLI and model, cwd, context stats; Fresh context, search, edit.
- **Agent form:** "New agent" or "Edit …"; Retire.

## Agent hover controls

`components/AgentInference.tsx` opens over agent avatars and names in chat, the DM header and conversation details. Pointer hover opens a frosted transparent glass panel; clicking or keyboard focus also exposes the controls. The provider remains a fixed identity. Model cards and the reasoning meter (one segment per mode, plus a **Provider default** toggle) come from `GET /agents/{id}/models`, including the agent's custom probe catalog. Apply sends `PATCH /agents/{id}/inference`; workspace state changes only when the server's agent frame arrives. Unsupported reasoning modes show automatic control by the CLI. The full agent form shows the same modes as a segmented control with a default option and a hint naming the chosen or default mode.

## Composer (`Composer.tsx`)

- **Mentions and commands:** `@` autocompletes channel members (not shown in DMs), and `/` lists `GET /commands`; commands run on the server.
- **Attachments:** files upload as soon as they're picked, pasted or dropped, and appear as removable chips. Removing a chip deletes the unsent upload.
- **Drafts:** kept in memory per channel.
- **Keys:** Enter sends, and Shift+Enter adds a newline.

## Deliberately omitted

- Voice input (the mic button): WebView2 has no built-in speech recognition. This is frontend work, not a backend gap.
- The × that cancels a single live tool call: no backend endpoint (D6).
- Per-tool durations from Claude (D3), and "cancelled by you" wording (D5).
- Tray icon, notifications and start at login: still unimplemented. The daemon lifecycle prerequisite (D1) is now available.

See [open gaps](../status/open-gaps.md).

## Agents tab cards

Each card in `DetailPanel.tsx` shows the agent's avatar without a status ring (the badge carries the status), then `AgentFacts`: **Now** (the server's activity summary, only when this is the agent's one active run), **Last run** in this channel (`GET /runs?limit=1`, refetched when one of its runs changes status; it opens the run in the Runs view), **Context** here (messages, tokens and window from the context frame) and **All channels** token use. Remove from the channel moved into a ⋯ menu with a confirmation dialog. In the sidebar footer, Quit sits apart at the right and hovers red. The composer starts at one line and grows as you type.

## Related

- [Timeline model](timeline-model.md) — the conversation rendering rules.
- [Live state](../backend/live-state.md) — the data each screen shows.
- [Design system](design-system.md) — the visual language.
- [Open gaps](../status/open-gaps.md) — why some elements are missing.

## Artefacts

`ArtefactsTab.tsx` and `PdfArtefact.tsx` add filesystem listings, rename/delete, Markdown, isolated HTML and PDF.js previews in the right panel. Opening the tab hides the left sidebar and uses half the desktop width; live announcements reopen the active file. See [channel artefacts](../backend/artefacts.md) (`20261021-artefacts`).
