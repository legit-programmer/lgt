---
id: 20261008-runtime-and-config
title: Runtime and configuration
tags: [backend, config]
created: 2026-10-08
updated: 2026-10-10
related: [20261008-explicit-configuration, 20261008-harness-adapters, 20261008-running-locally, 20261008-event-store, 20261010-desktop-daemon]
summary: How the backend starts (entry point, config loading, lock, harness scan, orchestrator start), every setting, and the data directory layout.
---

# Runtime and configuration

> Summary: How the backend starts (entry point, config loading, lock, harness scan, orchestrator start), every setting, and the data directory layout.

## Startup sequence

1. `python -m lgt --config <path> [--port 8000]` (`lgt/__main__.py`) runs Uvicorn bound to `127.0.0.1`, with one worker and `proxy_headers=False`.
2. `runtime.application` calls `load_config`, then wraps a `BackendRuntime` in `gateway.create_app`.
3. On app startup, `BackendRuntime.start` (`lgt/runtime.py`) runs these steps:
   1. Acquires `RuntimeLock` on `data_dir/workspace.lock` (`lgt/locking.py`). A second backend on the same data directory fails to start.
   2. Opens `Store` (`data_dir/workspace.sqlite3`), which applies `schema.sql` and `_migrate`.
   3. Builds `HarnessRegistry` and calls `scan()` to detect paths, versions, auth, models and capabilities.
   4. Builds `CLIRouter` and, when `checkpoint_mode` is `cli`, `CLISummarizer`.
   5. Builds the `Orchestrator` with the registry's runner factory and its `artifact_exists`.
   6. Calls `Orchestrator.start()`. That marks leftover active runs `failed` with code `orphaned`, replays the durable queue of every channel, and starts the attachment retention loop.
4. `BackendRuntime.__getattr__` forwards to the orchestrator, so the gateway treats the runtime as an orchestrator.

Desktop startup adds `--daemon --port 0`. The shell handles detached launch, while `lgt/daemon.py` publishes owner-private `daemon.json`, authenticates the API, and rotates daemon logs. See [Desktop daemon](desktop-daemon.md) for the lifecycle.

## Configuration file

`load_config` (`lgt/runtime.py`) accepts only these top-level keys: `settings`, `checkpoint_mode`, `codex_bin`, `claude_command`, `gemini_command`, and `codex_router_command`. Unknown keys are rejected.

**Required settings, with no defaults** (see [explicit configuration](../decisions/explicit-configuration.md)):

| Setting | Meaning |
| --- | --- |
| `data_dir` | Expands `~`. A relative path resolves beside the config file. |
| `max_hops` | The longest agent-to-agent mention chain. |
| `tool_output_cap` | Bytes of tool output stored per result. |
| `concurrent_runs` | The global run semaphore. |
| `replay_cap` | The WebSocket replay limit, which is also the live buffer size. |
| `router_timeout_seconds`, `router_context_events`, `router_model`, `codex_router_model`, `router_attempts` | Router behavior. |
| `session_ttl_seconds` | Null means sessions never expire. |
| `ndjson_line_limit` | The maximum length of one CLI output line. |
| `cancel_grace_seconds` | The wait before a forced kill. |
| `checkpoint_threshold`, `checkpoint_tail_chars`, `checkpoint_summary_chars` | Checkpoint sizing. |
| `attachment_max_bytes` | The per-upload limit. |

**Settings with defaults:**

| Setting | Default |
| --- | --- |
| `allowed_origins` | `[]` |
| `attachment_channel_quota_bytes` | `262144000` |
| `attachment_retention_seconds` | `86400` |
| `thumbnail_max_dimension` | `512` |

Two further rules:
- `route_after_active` is fixed to `false`. Setting it in the file is an error.
- `checkpoint_mode` must be `cli` or `deferred`.

`Settings.__post_init__` (`lgt/config.py`) validates types and ranges. For example, `checkpoint_tail_chars` must be smaller than `checkpoint_threshold`, and `allowed_origins` must be exact origins without wildcards.

## Data directory

| Path | Contents |
| --- | --- |
| `workspace.sqlite3` | The whole workspace state (WAL mode) |
| `workspace.lock` | The single-writer lock |
| `daemon.json` | Ready daemon PID, port, API version, launch token, and start time |
| `logs/daemon.log` | Rotating daemon diagnostics |
| `workspaces/<channel_id>/` | Managed channel directories |
| `attachments/<attachment_id>/<file>` | Uploads |
| `logs/<run_id>.stderr.log` | Per-run harness stderr, served by `GET /runs/{id}/log` |

## Related

- [Explicit configuration](../decisions/explicit-configuration.md) — why most settings have no defaults.
- [Harness adapters](harness-adapters.md) — what the startup scan discovers.
- [Running locally](../operations/running-locally.md) — a working config for development.
- [Event store](event-store.md) — what `Store` creates and migrates.
