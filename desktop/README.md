# Lgt desktop

The Lgt desktop app is a Tauri v2 shell around a React and TypeScript UI built with Vite. It renders the Ember screens in [`../design/`](../design/) against the local backend. Every state it shows comes from the backend: HTTP for the first load, then WebSocket frames for changes.

## Requirements

- Node.js 22 and pnpm 10
- Rust stable with the MSVC toolchain on Windows
- WebView2, which ships with Windows 10 and 11
- For development: Python 3.13 and `uv`, with `uv sync` run at the repository root. Release installers bundle the Python runtime.

## Allow the app's origin

The backend accepts only its own origin and exact origins listed in `settings.allowed_origins`. Generated desktop configuration includes the desktop origins. If you use an existing `config.local.json` or `LGT_CONFIG`, add the origins for the windows you use:

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

The shell discovers or starts a persistent backend on an available loopback port. A frosted overlay shows **Setting up your Lgt workspace** until the daemon and initial workspace state are ready. Startup errors provide a Retry button.

Closing the window leaves the daemon and agent runs active. The sidebar's **Quit Lgt** button shuts down the managed backend and exits. Reopening the app reconnects through `data_dir/daemon.json`; the shell verifies its launch token, PID, and API version before reuse.

Configuration is selected in this order:

1. `LGT_CONFIG`, an absolute path to an explicit backend configuration.
2. The repository's `config.local.json`, in development only.
3. `backend.json` in Tauri's application config directory, generated from `config.example.json` with the application data directory and desktop origins.

Existing configuration files are never rewritten. Set `LGT_BACKEND_URL` to use an externally managed loopback server instead of automatic launch. If that server uses daemon authentication, also set `LGT_BACKEND_TOKEN`. Quitting the desktop leaves an external server running. In a plain browser, `pnpm dev` uses `VITE_LGT_BACKEND_URL` and requires a manually started backend.

See [Desktop daemon lifecycle](../kb/topics/backend/desktop-daemon.md) for authentication and diagnostics. `--daemon` keeps Python in the foreground internally; the Tauri launcher detaches it and opens no console.

## Build an installer

```powershell
pnpm bundle
```

This uses `src-tauri/tauri.release.conf.json` to package a standalone Python runtime, production dependencies from `uv.lock`, and the backend source as Tauri resources. Build on the target operating system. End users do not need Python or `uv` installed. Installed harness CLIs still use the user's existing sign-ins.

`pnpm tauri build --no-bundle` builds the shell alone. Use the release configuration to include the backend when distributing the application.

## Test

```powershell
pnpm test        # UI state, daemon client, startup, timeline and formatting tests
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
| `src-tauri/` | The Rust shell: daemon discovery, detached startup, clean shutdown, and folder dialogs. `tauri.windows.conf.json` makes the Windows window frameless, and `src/components/TopBar.tsx` draws the combined title bar and app chrome. |

Agent avatars are DiceBear avatars (Critters by default), rendered locally from the `{style, seed}` the backend stores. Each style's definition loads on first use. Fonts are bundled, so the app works offline.
