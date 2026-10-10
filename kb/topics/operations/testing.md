---
id: 20261008-testing
title: Testing
tags: [ops, testing]
created: 2026-10-08
updated: 2026-10-10
related: [20261008-repo-map, 20261008-running-locally, 20261008-known-issues]
summary: How to run the backend and desktop test suites, which test file covers which module, the fakes they use, and how UI changes were verified visually.
---

# Testing

> Summary: How to run the backend and desktop test suites, which test file covers which module, the fakes they use, and how UI changes were verified visually.

## Commands

```powershell
uv run pytest -q                      # backend: about 150 tests, no model calls
cd desktop; pnpm test; pnpm typecheck # desktop: vitest unit tests + tsc
```

## Backend suite (`tests/`)

| File | Covers |
| --- | --- |
| `test_store.py`, `test_store_contracts.py` | Schema, triggers, migrations, summaries, search, usage |
| `test_orchestrator.py`, `test_orchestrator_contracts.py` | Queueing, coalescing, routing, hops, sessions, statuses, retirement, bootstrap |
| `test_channel_changes.py` | cwd changes, member removal, delivery cancellation, attachments (orchestrator level) |
| `test_channel_routes.py`, `test_gateway.py` | HTTP and WebSocket routes, origin policy, replay and resync |
| `test_context.py`, `test_checkpoints.py`, `test_summarizer.py` | Rendering, resume or cold, checkpoints |
| `test_router.py` | Router prompts, parsing, fallbacks |
| `test_codex_adapter.py`, `test_harnesses.py` | Adapters, discovery, validation |
| `test_processes.py`, `test_oneshot.py`, `test_locking.py` | Process trees, one-shot CLI, lock |
| `test_runtime.py`, `test_server.py`, `test_services.py` | Config loading, the real app boot, catalogs |
| `test_daemon.py` | Private descriptor ownership, HTTP and WebSocket authentication, dynamic-port readiness, duplicate launch, and shutdown |

## Fakes

The fakes and helpers come from `tests/support.py` and the `tests/fake_*.py` files:
- `ControlledFactory` / `ControlledRunner` script runner output step by step;
- `FakeRouter` returns fixed picks;
- `fake_codex_app_server.py` and `fake_codex_sdk_server.py` stand in for Codex through the real SDK;
- `fake_streaming_cli.py` stands in for the Claude, Gemini and custom NDJSON CLIs.

Use `settings(tmp_path, **overrides)` to build a valid `Settings` object.

## Desktop suite (`desktop/src/**/*.test.ts`)

- `lib/timeline.test.ts`: block building rules.
- `store/workspace.test.ts`: frame reducer, partials, runs, snapshots.
- `lib/format.test.ts`: formatting and argv splitting.
- `api/client.test.ts`: shared launch attempts, retry, token refresh, authenticated HTTP and media, and browser compatibility.
- `App.test.tsx`: loading through daemon and workspace startup, StrictMode deduplication, string errors, and Retry.

Rust daemon tests live in `desktop/src-tauri/src/daemon.rs`. Run them with `cargo test --lib` from `desktop/src-tauri` when changing discovery or process launch.

## Visual verification

The UI was checked against a live backend with headless Edge:
- `msedge --headless=new --screenshot` for static views, using hash routes such as `#/c/<id>` and `#/agents/new`;
- a small Chrome DevTools Protocol script for clicking, typing and attaching files.

These scripts are not in the repo. Recreate them in a scratch folder if needed. Use a scratch `data_dir`, because real runs call models.

The startup overlay was also checked in headless Edge at 1440 x 900 (dark) and 1024 x 640 (light), with backend requests held pending. Reduced-motion emulation produced no active overlay animations.

## Related

- [Repo map](../overview/repo-map.md) — the modules under test.
- [Running locally](running-locally.md) — starting a backend for manual checks.
- [Known issues](../status/known-issues.md) — flaky or environment-dependent tests.
