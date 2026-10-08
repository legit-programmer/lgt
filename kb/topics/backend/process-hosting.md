---
id: 20261008-process-hosting
title: Process hosting
tags: [backend, process]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-harness-adapters, 20261008-run-lifecycle, 20261008-routing, 20261008-known-issues]
summary: How CLI child processes are spawned without a shell, grouped so the whole tree can be killed (Windows Job Objects, POSIX process groups), and bounded; plus the Codex SDK byte host and one-shot CLI calls.
---

# Process hosting

> Summary: How CLI child processes are spawned without a shell, grouped so the whole tree can be killed (Windows Job Objects, POSIX process groups), and bounded; plus the Codex SDK byte host and one-shot CLI calls.

## Files

| File | Role |
| --- | --- |
| `lgt/processes.py` | `spawn_command`, `ProcessTree` (terminate with a grace period), `read_lines` (bounded NDJSON lines), Windows Job Object helpers, and the `--lgt-launcher` re-exec |
| `lgt/sdk_host.py` | A byte-level stdio host between the Codex SDK and `codex app-server`. It forwards traffic unchanged, caps line length, writes stderr to the run log, and owns the Job Object on Windows. |
| `lgt/oneshot.py` | `invoke_cli` and `make_cli_invoker`, which the router and summarizer use for one-shot prompts: argv only, prompt on stdin, bounded output, timeout, and process-tree cleanup |

## Rules

- **Never use a shell.** Commands are argv arrays and prompts travel on stdin, so there is no interpolation.
- **The whole tree dies together.**
  - Windows assigns each child to a Job Object, and the SDK host closes its job when the backend's stdin reaches EOF.
  - POSIX starts children in their own process group and kills the group.
- **Bounded output:** stdout lines are capped by `ndjson_line_limit`, and one-shot output by a byte limit. Exceeding the limit fails the call rather than truncating it silently.
- **Child processes are started with `sys.executable`.** Both the launcher and `sdk_host.py` are run this way, which matters for packaging: a frozen PyInstaller or Nuitka executable breaks this, so ship a real interpreter instead.

## Related

- [Harness adapters](harness-adapters.md) — the main users of `spawn_command`.
- [Run lifecycle](run-lifecycle.md) — cancellation and orphan recovery.
- [Routing](routing.md) — `invoke_cli` for router calls.
- [Known issues](../status/known-issues.md) — packaging caveat.
