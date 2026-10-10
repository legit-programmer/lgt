---
id: 20261008-running-locally
title: Running locally
tags: [ops, config]
created: 2026-10-08
updated: 2026-10-10
related: [20261010-desktop-daemon, 20261008-runtime-and-config, 20261008-origins-and-media, 20261008-testing]
summary: Step-by-step commands to run the backend and the desktop app together for development, including the config the desktop needs and how to point the app at another backend.
---

# Running locally

> Summary: Step-by-step commands to run the backend and the desktop app together for development, including the config the desktop needs and how to point the app at another backend.

## Prerequisites

- Python 3.13 with `uv`.
- Node.js 22 with pnpm 10, and Rust stable (MSVC on Windows) for the desktop app.
- At least one harness CLI that is installed and signed in. The Codex CLI ships with the pinned SDK; Claude Code or Gemini are optional.

## Backend

```powershell
uv sync
Copy-Item config.example.json config.local.json   # gitignored
# edit config.local.json: data_dir, and add the desktop origins:
#   "allowed_origins": ["http://tauri.localhost", "tauri://localhost", "http://localhost:1420"]
uv run python -m lgt --config config.local.json   # http://127.0.0.1:8000, docs at /docs
```

- Use `--port` for another port.
- Each data directory allows one backend at a time, because of the lock. Use a separate `data_dir` for experiments.

## Desktop

```powershell
cd desktop
pnpm install
pnpm tauri dev                       # Tauri window, Vite on :1420
# or, in a browser:
$env:VITE_LGT_BACKEND_URL = "http://127.0.0.1:8000"; pnpm dev
```

The Tauri shell starts the backend automatically. `LGT_CONFIG` selects an absolute configuration path; otherwise development uses `config.local.json` when present. Without either, the shell generates `backend.json` in its application config directory and uses its application data directory. Existing configurations must include the desktop origins and are not rewritten.

`LGT_BACKEND_URL` selects an externally managed loopback backend. Add `LGT_BACKEND_TOKEN` if that backend uses daemon authentication. Normal close leaves the managed daemon active; the sidebar's **Quit Lgt** stops it. Browser development still requires manual backend startup.

## Builds

- `pnpm bundle` builds installers with the standalone Python runtime, locked production dependencies, and backend source. It uses `src-tauri/tauri.release.conf.json`.
- `pnpm tauri build --no-bundle` builds only the shell. Distribute a build made with the release configuration to include the backend.

## Things that cost model usage

Each of these calls a real model on your account:
- sending a message;
- routing an unmentioned channel message (Claude Haiku by default);
- **Try asking** suggestions;
- checkpoint summaries, when `checkpoint_mode` is `cli`.

Use a scratch `data_dir` and cwd for experiments.

## Related

- [Runtime and configuration](../backend/runtime-and-config.md) — every setting.
- [Origins and media](../desktop/origins-and-media.md) — why the origins are required.
- [Testing](testing.md) — test suites that need no model calls.
