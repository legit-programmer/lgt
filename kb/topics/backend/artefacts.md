---
id: 20261021-artefacts
title: Channel artefacts
tags: [backend, desktop, api, security]
created: 2026-10-21
updated: 2026-10-21
related: [20261008-context-and-sessions, 20261008-gateway-http, 20261008-screens]
summary: Filesystem artefacts, agent announcements, isolated previews and channel viewer.
---

# Channel artefacts

`lgt/artefacts.py` owns setup, safe paths, recursive discovery, metadata, bounded
reads and complete `lgt-artefact` messages. Each channel uses its current
`<cwd>/.lgt/artefacts/<channel_id>`; filenames are identities, not database rows.
External rename/removal is reflected by subsequent listings. Cwd changes select
the new folder; old files remain untouched. Files are never relocated automatically.

`Orchestrator._execute` sets up and injects instructions before every turn.
`_output` validates announcements after message completion and publishes the
live-only `artefact_open` frame for both creation and update. The persisted message
also retains metadata for history. `mutate_artefact` serializes rename/delete in the
mailbox and publishes `artefact_changed`.

`gateway.py` exposes authenticated list/content/mutations and HTML preview tickets.
The short-lived single-use preview route is the sole artefact authentication
exception; its response is always sandboxed with no same-origin privileges.
HTTPS external assets work, but fetch, forms, nested frames and native commands do
not. See [API reference](../../../docs/backend-reference.md#channel-artefacts).

Related: [context](context-and-sessions.md), [gateway](gateway-http.md),
[screens](../desktop/screens.md).

## Desktop viewer

`ArtefactsTab.tsx` lists the channel folder, rechecking every three seconds while
visible and on backend notifications. Selection is scoped to channel and cwd.
Missing files show a recoverable message; the list always reflects current disk
contents. Rename/delete use dialogs and follow backend events, not optimistic
state. Historical artefact messages have an Open button.

`DetailPanel` adds Artefacts alongside Agents and Runs. Opening it hides the left
sidebar and divides the desktop equally between chat and viewer. Phone layouts
show the viewer full-width with a close action. Live creation and update frames
open/reopen the active channel's file; other channels get a toast without navigation.
Replayed durable messages do not steal focus.

Markdown reuses React Markdown/GFM. HTML uses a sandboxed iframe pointing at a
single-use server preview capability, never srcdoc or the app's own origin.
`PdfArtefact.tsx` lazy-loads PDF.js with page and zoom controls; the worker, CMaps,
fonts and wasm decoders are bundled locally by the Vite `pdfjs-assets` plugin.
The desktop CSP permits preview frames and the bundled PDF worker; it does not
permit arbitrary inline scripts in the main app.
