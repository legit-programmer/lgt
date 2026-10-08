---
id: 20261008-desktop-architecture
title: Desktop architecture
tags: [desktop]
created: 2026-10-08
updated: 2026-10-09
related: [20261008-client-state, 20261008-screens, 20261008-design-system, 20261008-origins-and-media, 20261008-no-frontend-workarounds, 20261008-open-gaps, 20261008-timeline-model]
summary: How the Tauri shell, the React app, and the backend connect, the boot sequence, and a file map of desktop/.
---

# Desktop architecture

> Summary: How the Tauri shell, the React app, and the backend connect, the boot sequence, and a file map of desktop/.

## Shape

```
Tauri shell (Rust, desktop/src-tauri) ── hosts ──> WebView2 / WKWebView
   │ commands: backend_url()                         │
   │ plugins: dialog (folder picker), opener         ▼
   └──────────────────────────────────────> React app (desktop/src)
                                               │ HTTP actions (fetch)
                                               │ WebSocket /ws (state)
                                               ▼
                                         Lgt backend on 127.0.0.1
```

- **The shell is thin.** `src-tauri/src/lib.rs` registers the dialog and opener plugins and one command, `backend_url`, which returns `LGT_BACKEND_URL` or `http://127.0.0.1:8000`. It does **not** start or stop the backend; that needs the daemon handshake (D1 in [open gaps](../status/open-gaps.md)).
- **Security:**
  - `src-tauri/tauri.conf.json` sets a strict CSP: `connect-src` and `img-src` allow only loopback.
  - `capabilities/default.json` grants only `dialog:allow-open`, `opener:allow-open-url` and `core:window:allow-set-effects`.
- **Identifier and window:** the identifier is `com.lgt.desktop`, and the main window label is `main`.
- **Window glass:** the main window is `transparent` with `windowEffects` `["acrylic", "underWindowBackground"]`. `lib/windowGlass.ts` re-applies the effect with a theme tint whenever the theme changes. See the [design system](design-system.md).

## Boot sequence (`src/App.tsx`)

1. `resolveBackendUrl()` (`src/api/client.ts`) asks the Tauri `backend_url` command. In a plain browser it reads `VITE_LGT_BACKEND_URL`.
2. `useWorkspace.boot()` loads agents, channel summaries, agent statuses and the profile in parallel.
3. `workspaceSocket.start()` opens `/ws` with the cursor.
4. The workspace renders. With no agents it opens onboarding; otherwise the most recent conversation, unless the URL hash names a view.
5. If the backend can't be reached, the app shows `Unreachable`, with the start command and a Retry button.

## File map (`desktop/src`)

| Path | Role |
| --- | --- |
| `main.tsx` | Fonts, CSS, React Query and Radix tooltip providers |
| `App.tsx` | Boot, routing between views, Ctrl/⌘ K, global dialogs, toasts |
| `api/types.ts`, `api/client.ts` | API types and the typed `api.*` client with the `ApiError` envelope |
| `store/workspace.ts` | Workspace state and `applyFrame` ([client state](client-state.md)) |
| `store/socket.ts` | WebSocket lifecycle |
| `store/ui.ts` | View, panel, palette, theme, and URL hash sync |
| `lib/timeline.ts` | Event log → blocks ([timeline model](timeline-model.md)) |
| `lib/format.ts`, `lib/agents.ts`, `lib/media.ts`, `lib/folder.ts`, `lib/useNow.ts` | Formatting, hues and CLI labels, blob media, folder dialog, ticking clock |
| `components/` | `Avatar` (DiceBear), `Status` (dots, badges, elapsed), `Markdown` (mentions), `Toasts` |
| `features/` | Screens; see [screens](screens.md) |
| `styles/` | `tokens.css`, `components.css`, `app.css` ([design system](design-system.md)) |

## Libraries

| Library | Used for |
| --- | --- |
| React 19, TypeScript 7, Vite 8 | The app and build |
| Zustand | Workspace and UI stores |
| TanStack Query | Catalogs and run lists |
| Radix | Dialog, popover, dropdown, tooltip behavior |
| `cmdk` | The palette |
| `lucide-react` | Icons |
| `react-markdown` + `remark-gfm` | Message rendering |
| `@dicebear/core` + `@dicebear/collection` 9.x | Avatars, rendered offline |
| `@fontsource` | Figtree and IBM Plex Mono, bundled |

## Related

- [Client state](client-state.md) — the data layer in detail.
- [Screens](screens.md) — which file implements which design screen.
- [Design system](design-system.md) — tokens and component classes.
- [Origins and media](origins-and-media.md) — CSP, allowed origins, blob media.
- [No frontend workarounds](../decisions/no-frontend-workarounds.md) — the rule behind the data layer.
