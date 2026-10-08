# Lgt desktop

The Lgt desktop app is a Tauri v2 shell around a React and TypeScript UI built with Vite. It renders the Ember screens in [`../design/`](../design/) against the local backend. Every state it shows comes from the backend: HTTP for the first load, then WebSocket frames for changes.

## Requirements

- Node.js 22 and pnpm 10
- Rust stable with the MSVC toolchain on Windows
- WebView2, which ships with Windows 10 and 11
- A running Lgt backend. See the [root README](../README.md).

## Allow the app's origin

The backend accepts only its own origin and exact origins listed in `settings.allowed_origins`. Add the origins for the windows you use to `config.local.json`:

```json
"allowed_origins": ["http://tauri.localhost", "tauri://localhost", "http://localhost:1420"]
```

| Origin | Used by |
| --- | --- |
| `http://tauri.localhost` | The built app on Windows |
| `tauri://localhost` | The built app on macOS and Linux |
| `http://localhost:1420` | `pnpm tauri dev` and `pnpm dev` |

## Run

```powershell
pnpm install
pnpm tauri dev
```

The shell connects to `http://127.0.0.1:8000`. Set `LGT_BACKEND_URL` before starting the shell to use another address. In a plain browser, `pnpm dev` reads `VITE_LGT_BACKEND_URL` instead.

The shell does not start or stop the backend yet; it needs the daemon handshake listed as D1 in [backend gaps](../design/backend-gaps.md). When the backend can't be reached, the app shows the command to start it and a retry button.

## Build

```powershell
pnpm tauri build
```

`pnpm tauri build --no-bundle` builds only `src-tauri/target/release/lgt-desktop.exe`, without installers.

## Test

```powershell
pnpm test        # timeline, store and formatting unit tests
pnpm typecheck
```

## Layout

| Path | Contents |
| --- | --- |
| `src/styles/tokens.css` | Ember tokens for dark and light themes |
| `src/styles/components.css` | `fv-` components from the design README |
| `src/api/` | Typed HTTP client and API types |
| `src/store/workspace.ts` | Workspace state built from HTTP snapshots and socket frames |
| `src/store/socket.ts` | Cursor replay, resync and reconnect |
| `src/lib/timeline.ts` | Event log to timeline blocks: runs, tool groups, notices |
| `src/features/` | Sidebar, channel and DM views, detail panel, agent form, onboarding, command palette |
| `src-tauri/` | The Rust shell: folder dialogs and the backend URL. `tauri.windows.conf.json` makes the Windows window frameless, and `src/components/TopBar.tsx` draws the combined title bar and app chrome. |

Agent avatars are DiceBear avatars, rendered locally from the `{style, seed}` the backend stores. Fonts are bundled, so the app works offline.
