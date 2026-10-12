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
| `http://tauri.localhost` | The built app on Windows and Android |
| `tauri://localhost` | The built app on macOS, Linux and iOS |
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

Existing configuration files are never rewritten. Set `LGT_BACKEND_URL` to an externally managed HTTP(S) server instead of automatic launch and `LGT_BACKEND_TOKEN` to its credential when authentication is enabled. Quitting the desktop leaves an external server running. In a plain browser, `pnpm dev` uses `VITE_LGT_BACKEND_URL` and requires a manually started backend.

## Pair devices

Configure the host backend's `listen_host: "0.0.0.0"`, a stable `listen_port`, and a reachable `advertised_url`. The launcher uses that configured port for remote access; local-only desktop launches retain their dynamically allocated port. Restart the backend after changing these settings. See [remote access configuration](../docs/backend-reference.md#device-pairing-and-remote-access).

**Settings → Devices** is available only to a desktop authenticated as the local administrator. Name a connection and choose **Pair device**. The QR contains the address and persistent device credential; **Copy pairing code** copies the same JSON. The code is returned only when created, and cannot be recovered from the device list. Revocation disconnects all sockets using that credential and rejects future requests.

**Connect to a workspace** verifies a pasted code and stores it under `lgt.pairedConnection` in local storage. Stored pairing takes precedence over local daemon startup and environment overrides. HTTP, media fetches, and the WebSocket handshake authenticate with that device credential. **Use local workspace** forgets it and reloads the default connection. Quitting a paired client exits that client without stopping a daemon. Remote workspace folder paths refer to the host computer.

The Android and iOS apps scan the same QR code; see [Mobile](#mobile-android-and-ios).

See [Desktop daemon lifecycle](../kb/topics/backend/desktop-daemon.md) for authentication and diagnostics. `--daemon` keeps Python in the foreground internally; the Tauri launcher detaches it and opens no console.

## Build an installer

```powershell
pnpm bundle
```

This uses `src-tauri/tauri.release.conf.json` to package a standalone Python runtime, production dependencies from `uv.lock`, and the backend source as Tauri resources. Build on the target operating system. End users do not need Python or `uv` installed. Installed harness CLIs still use the user's existing sign-ins.

`pnpm tauri build --no-bundle` builds the shell alone. Use the release configuration to include the backend when distributing the application.

## Mobile (Android and iOS)

The same app builds for phones as a paired-only client. A phone has no local workspace: the daemon launcher is compiled out, and the first launch shows **Pair with your workspace**. Create a connection in **Settings → Devices** on the workspace computer, then choose **Scan QR code** on the phone. **Disconnect** in the connection dialog forgets the pairing.

The workspace must be reachable from the phone, and its `allowed_origins` must include the phone's webview origin from the table above. Android release builds and iOS refuse plain-HTTP addresses, so use an HTTPS `advertised_url` for anything beyond Android debug builds.

```sh
# Android: Android Studio or the SDK command-line tools, an NDK, and ANDROID_HOME / NDK_HOME
rustup target add aarch64-linux-android armv7-linux-androideabi i686-linux-android x86_64-linux-android
pnpm android:dev                   # device or emulator, with Vite on TAURI_DEV_HOST
pnpm android:build                 # signed release needs a keystore; see the Tauri docs

# iOS: macOS with Xcode
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
pnpm tauri ios init                # generates src-tauri/gen/apple once; commit it
pnpm tauri icon src-tauri/icons/icon.png   # then restore the desktop icons it rewrites, keeping gen/apple's
pnpm ios:dev
```

If a dev build's requests fail with `403 forbidden_origin`, the webview is loading the Vite server directly; add its origin (for example `http://192.168.1.20:1420`) to `allowed_origins` for development. `src-tauri/gen/android` is committed. `src-tauri/Info.ios.plist` is merged into the generated iOS project. See [Mobile client](../kb/topics/desktop/mobile-client.md) for how the build differs from desktop.

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
| `src-tauri/` | The Rust shell: daemon discovery, detached startup, clean shutdown, and folder dialogs (desktop); QR scanning and file saving (mobile). `capabilities/default.json` is desktop-only and `capabilities/mobile.json` is mobile-only; `gen/android` is the generated Android project. `tauri.windows.conf.json` makes the Windows window frameless, and `src/components/TopBar.tsx` draws the combined title bar and app chrome. |

Agent avatars are DiceBear avatars (Critters by default), rendered locally from the `{style, seed}` the backend stores. Each style's definition loads on first use. Fonts are bundled, so the app works offline.
