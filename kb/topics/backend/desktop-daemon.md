---
id: 20261010-desktop-daemon
title: Desktop daemon lifecycle
tags: [backend, desktop, process, security, config]
created: 2026-10-10
updated: 2026-10-10
related: [20261008-runtime-and-config, 20261008-desktop-architecture, 20261008-gateway-http, 20261008-websocket-protocol, 20261008-running-locally]
summary: How the desktop discovers, starts, authenticates to, and shuts down its persistent local backend.
---

# Desktop daemon lifecycle

The Tauri shell owns startup. The backend owns workspace state and publishes its connection details only when ready.

## Start and reconnect

`desktop/src-tauri/src/daemon.rs` implements the `ensure_backend` command registered in `lib.rs`. The desktop API client awaits it before loading workspace state. Concurrent startup calls share an attempt, and the Python `RuntimeLock` prevents duplicate writers across app processes.

The shell reads `data_dir/daemon.json` and verifies its token, PID, application identity, and API version through `/health`. It launches a backend if no live daemon is available. The backend command is:

```powershell
python -m lgt --config <absolute-config-path> --port 0 --daemon
```

The shell launches without a console and redirects standard streams to files. Closing the window leaves the daemon running. `--daemon` itself serves in the foreground, so another process manager can also host it.

On Windows, `spawn_detached` requests a new process group, no console, and job breakaway. If a development host denies breakaway, launch falls back to a hidden process in the inherited job. That host can still terminate its descendants. The installed app launched normally is independent of a development host. See [Windows process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags).

## Discovery record (`lgt/daemon.py`)

`DaemonServer.startup` writes this record after ASGI startup and socket binding:

```json
{"pid":1234,"port":49152,"api_version":1,"token":"<per-launch-secret>","started_at":"2026-10-10T00:00:00+00:00"}
```

`DaemonState.publish` writes to an owner-private temporary file, flushes it, and atomically replaces `daemon.json`. POSIX uses mode `0600`. Windows uses a protected owner-and-SYSTEM DACL. The token is generated for each launch and never passed on the command line.

`DaemonState.remove` deletes only a descriptor whose PID and token match the current process. Normal shutdown removes discovery before releasing the workspace lock. A stale descriptor after a crash does not prove a process is alive. Never kill a PID solely because it appears in this file.

## Authentication and shutdown

- HTTP requests, including `/health`, require `Authorization: Bearer <token>` in daemon mode. Origin and loopback checks still apply.
- The first WebSocket frame is `{"last_id":n,"token":"<token>"}`. Authentication must finish within five seconds, before replay or snapshots.
- `POST /shutdown` returns `{"status":"stopping"}` and requests graceful Uvicorn shutdown. Runtime cleanup stops runs and closes SQLite.
- Manual startup without `--daemon` preserves the unauthenticated local development API. `/shutdown` is unavailable in that mode.

`desktop/src/api/client.ts` keeps the token in memory. Requests and media use `fetchBackendResource`; WebSocket startup uses `socketHandshake`. Credentials are never appended to URLs or stored in browser storage. Cross-origin resource requests and redirects are rejected.

The sidebar's **Quit Lgt** action invokes `quit_workspace`. Normal window close keeps background runs alive. An explicitly configured external backend stays running when the desktop quits.

Shutdown distinguishes a refused connection from authentication, malformed-response, and timeout errors. An unverified shutdown keeps the window open with an error so the user can retry.

## Launch screen and diagnostics

`StartupOverlay` covers the workspace while discovery and the initial state load are pending. Its abstract background contains no workspace data. CSS frost and an animated mark accompany **Setting up your Lgt workspace**. Reduced-motion preferences stop the animation, and the title bar remains available.

Startup errors show a Retry action. Python daemon logs rotate at 5 MiB with three backups under `data_dir/logs/daemon.log`.

## Related

- [Runtime and configuration](runtime-and-config.md) — explicit settings and the single-writer lock.
- [Desktop architecture](../desktop/desktop-architecture.md) — boot sequence and UI ownership.
- [Gateway HTTP](gateway-http.md) — authentication, origins, and routes.
- [WebSocket protocol](websocket-protocol.md) — authenticated replay handshake.
- [Running locally](../operations/running-locally.md) — configuration overrides and packaging commands.
