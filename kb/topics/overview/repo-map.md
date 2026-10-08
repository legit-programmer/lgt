---
id: 20261008-repo-map
title: Repo map
tags: [overview]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-system-overview, 20261008-desktop-architecture, 20261008-testing, 20261008-runtime-and-config, 20261008-glossary, 20261008-event-store, 20261008-dispatch-and-queue, 20261008-run-lifecycle, 20261008-context-and-sessions, 20261008-routing, 20261008-harness-adapters, 20261008-process-hosting, 20261008-attachments, 20261008-gateway-http, 20261008-websocket-protocol, 20261008-screens]
summary: Every top-level folder and backend module with its responsibility, so you know which file to open for a given concern.
---

# Repo map

> Summary: Every top-level folder and backend module with its responsibility, so you know which file to open for a given concern.

## Top level

| Path | Contents |
| --- | --- |
| `lgt/` | Backend package. Run it with `python -m lgt --config <file>`. |
| `tests/` | Backend pytest suite and fakes (`fake_codex_app_server.py`, `fake_codex_sdk_server.py`, `fake_streaming_cli.py`, `support.py`). |
| `desktop/` | Tauri desktop app. See [desktop architecture](../desktop/desktop-architecture.md). |
| `design/` | Ember design README, `Lgt Screens.pdf`, and `backend-gaps.md` (the open contracts plus the implemented checklist). |
| `docs/` | `backend-reference.md` (the authoritative API reference) and `custom-harness.md` (the stdio protocol). |
| `kb/` | This knowledge base. |
| `Multi-Agent Workspace — Backend Spec.md` | The original backend spec. Some rules have since been superseded; see [decisions](../decisions/_topic.md). |
| `config.example.json` | Settings template. Copy it to the gitignored `config.local.json`. |
| `pyproject.toml`, `uv.lock` | Python dependencies, managed with uv. `openai-codex` is pinned to `0.160.1`. |

## Backend modules (`lgt/`)

| File | Responsibility | KB note |
| --- | --- | --- |
| `__main__.py` | CLI entry point: `--config`, `--port`; Uvicorn on `127.0.0.1` with one worker | [runtime](../backend/runtime-and-config.md) |
| `runtime.py` | `load_config`, `BackendRuntime` (opens the store, scans harnesses, builds the orchestrator) | [runtime](../backend/runtime-and-config.md) |
| `config.py` | `Settings` dataclass and its validation | [runtime](../backend/runtime-and-config.md) |
| `locking.py` | `RuntimeLock`: one backend per data directory | [runtime](../backend/runtime-and-config.md) |
| `models.py` | Dataclasses (`Agent`, `Channel`, `Event`, `Run`, `Session`, `QueueItem`, `Attachment`, `Turn`), protocols, `new_id` (ULID) | [glossary](glossary.md) |
| `schema.sql`, `store.py` | SQLite schema, migrations, triggers, FTS search, summaries, usage | [event store](../backend/event-store.md) |
| `orchestrator.py` | Mailboxes, queue pump, routing, dispatch, run execution, state frames, checkpoints | [dispatch](../backend/dispatch-and-queue.md), [run lifecycle](../backend/run-lifecycle.md) |
| `context.py` | Prompt rendering, session resume or cold plan | [context](../backend/context-and-sessions.md) |
| `router.py` | `CLIRouter`: Claude, then Codex, routing and suggestions | [routing](../backend/routing.md) |
| `summarizer.py` | `CLISummarizer` for checkpoint summaries | [context](../backend/context-and-sessions.md) |
| `harnesses.py` | `HarnessRegistry`: discovery, catalogs, agent validation, runner factory | [harness adapters](../backend/harness-adapters.md) |
| `codex_adapter.py` | Codex app-server runner (official SDK) | [harness adapters](../backend/harness-adapters.md) |
| `streaming_adapter.py` | Claude, Gemini and custom NDJSON runners | [harness adapters](../backend/harness-adapters.md) |
| `processes.py`, `sdk_host.py`, `oneshot.py` | Process trees, Windows Job Objects, Codex byte host, one-shot CLI calls | [process hosting](../backend/process-hosting.md) |
| `run_errors.py` | Structured failure errors and failure text | [run lifecycle](../backend/run-lifecycle.md) |
| `attachments.py` | Upload storage, filename sanitizing, size cap | [attachments](../backend/attachments.md) |
| `gateway.py` | FastAPI app: HTTP routes, origin policy, WebSocket endpoint | [gateway HTTP](../backend/gateway-http.md), [WebSocket](../backend/websocket-protocol.md) |
| `broadcast.py` | `EventBus`: in-process fan-out with overflow handling | [WebSocket](../backend/websocket-protocol.md) |
| `services.py` | Slash command registry and starter templates | [routing](../backend/routing.md), [screens](../desktop/screens.md) |

## Related

- [System overview](system-overview.md) — prerequisite: how the pieces interact.
- [Desktop architecture](../desktop/desktop-architecture.md) — the `desktop/` map.
- [Testing](../operations/testing.md) — which test file covers which module.
