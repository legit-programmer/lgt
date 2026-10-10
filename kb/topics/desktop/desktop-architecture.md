---
id: 20261008-desktop-architecture
title: Desktop architecture
tags: [desktop]
created: 2026-10-08
updated: 2026-10-10
related: [20261010-desktop-daemon, 20261008-client-state, 20261008-screens, 20261008-design-system, 20261008-origins-and-media, 20261008-no-frontend-workarounds, 20261008-open-gaps, 20261008-timeline-model]
summary: How the Tauri shell, the React app, and the backend connect, the boot sequence, and a file map of desktop/.
---

# Desktop architecture

> Summary: How the Tauri shell, the React app, and the backend connect, the boot sequence, and a file map of desktop/.

## Shape

```
Tauri shell (Rust, desktop/src-tauri) ── hosts ──> WebView2 / WKWebView
   │ commands: ensure_backend()                         │
   │ plugins: dialog (folder picker), opener         ▼
   └──────────────────────────────────────> React app (desktop/src)
                                               │ HTTP actions (fetch)
                                               │ WebSocket /ws (state)
                                               ▼
                                         Lgt backend on 127.0.0.1
```

- **The shell owns backend startup.** `src-tauri/src/lib.rs` registers `ensure_backend` and `quit_workspace`, implemented in `src-tauri/src/daemon.rs`. Discovery verifies the private `daemon.json` descriptor over authenticated HTTP or starts a detached backend. Closing the window preserves the daemon; **Quit Lgt** shuts it down. See [Desktop daemon](../backend/desktop-daemon.md).
- **Security:**
  - `src-tauri/tauri.conf.json` sets a strict CSP: `connect-src` and `img-src` allow only loopback.
  - `capabilities/default.json` grants folder picking, URL opening, and title-bar window controls. Daemon launch stays in Rust commands; the frontend gets no arbitrary shell execution permission.
- **Identifier and window:** the identifier is `com.lgt.desktop`, and the main window label is `main`.
- **Top bar (title bar and app chrome in one row):**
  - On Windows, `src-tauri/tauri.windows.conf.json` overrides the window with `decorations: false`. Tauri merges it over `tauri.conf.json`, and arrays are replaced whole, so it repeats the full window entry.
  - `components/TopBar.tsx` lays out three zones. The lead zone, over the sidebar column, holds the sidebar toggle, back/forward and the "new" menu. The middle holds the view's title. The right holds the view's actions, then the window controls (only when `isDecorated()` is false).
  - Screens fill the title and actions through `<TopBarSlot target="title" | "actions">`, a portal into the bar. Plain text in the bar has `pointer-events: none` (`.topbar-passive`), so it drags the window; double-click maximizes.
  - Permissions: `core:window:allow-minimize`, `allow-toggle-maximize`, `allow-close`, `allow-start-dragging`.
  - `App.tsx` wraps every state (splash, unreachable, workspace) in `.app-shell`, so the window stays movable and closable on the error screen.

## Boot sequence (`src/App.tsx`)

1. `StartupOverlay` shows the frosted loading screen. `resolveBackendUrl()` (`src/api/client.ts`) awaits the Tauri `ensure_backend` command and stores its URL and launch token in memory. In a plain browser it reads `VITE_LGT_BACKEND_URL`.
2. `useWorkspace.boot()` loads agents, channel summaries, agent statuses and the profile in parallel.
3. `workspaceSocket.start()` opens `/ws` with the cursor and launch token in its first frame.
4. The workspace renders. With no agents it opens onboarding; otherwise the most recent conversation, unless the URL hash names a view.
5. Startup failure replaces the overlay with its error and a Retry button. Retry repeats discovery. Concurrent boot attempts share one promise, including React StrictMode effect replay.

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
| `components/StartupOverlay.tsx`, `StartupOverlay.css` | Frosted launch screen, animated mark, reduced-motion styles |
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
| `@dicebear/core` 10 + `@dicebear/styles` 10 | Avatars, rendered offline. Each style's JSON definition is its own lazy chunk, loaded on first use. |
| `@fontsource` | Figtree and IBM Plex Mono, bundled |

## Related

- [Client state](client-state.md) — the data layer in detail.
- [Screens](screens.md) — which file implements which design screen.
- [Design system](design-system.md) — tokens and component classes.
- [Origins and media](origins-and-media.md) — CSP, allowed origins, blob media.
- [No frontend workarounds](../decisions/no-frontend-workarounds.md) — the rule behind the data layer.
