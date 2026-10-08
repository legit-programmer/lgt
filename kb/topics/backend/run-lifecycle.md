---
id: 20261008-run-lifecycle
title: Run lifecycle
tags: [backend, runs]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-dispatch-and-queue, 20261008-harness-adapters, 20261008-context-and-sessions, 20261008-live-state]
summary: Run statuses and the events they emit, how runner output becomes log events, cancellation, failure normalization, and orphan recovery after a crash.
---

# Run lifecycle

> Summary: Run statuses and the events they emit, how runner output becomes log events, cancellation, failure normalization, and orphan recovery after a crash.

## Statuses

`queued` → `starting` → `running` → one of `completed`, `failed` or `cancelled`. Each transition appends a `run_status` event whose payload comes from `_run_payload`: `run_id`, `agent_id`, `status`, `started_at`, `ended_at` and `duration_ms`. Failures add a structured `error` and a human-readable `text`.

## Execution (`Orchestrator._execute`)

1. It waits on the global run semaphore. If the run is cancelled while waiting, it finishes as `cancelled`.
2. It marks the run `starting` and creates the managed cwd if needed.
3. It gets a runner from `runner_factory(harness)`, which is `HarnessRegistry.runner`, and iterates `runner.start(turn)`.
4. Each `NormalizedEvent` passes through `_output` inside the channel mailbox:

| Runner event | Effect |
| --- | --- |
| `process_started` | Stores the pgid or pid. |
| `run_started` | Stores `harness_session_id`; the status becomes `running`. |
| `text_delta` | Appended to the in-memory partial and published as a `delta` frame. **Not stored.** |
| `message` | Appended as an agent `message` with `author_handle` and mentions. Clears the partial. Mentioned members are enqueued, up to `max_hops`. |
| `tool_call`, `tool_result` | Appended. They also update the agent's live activity. |
| `usage` | Accumulates the token counters and context usage on the run, then publishes `usage` and `context` frames. |
| `limits` / `rate_limits` | Stores a `harness_limits` snapshot and publishes `harness_limits`. |
| `run_finished` | Finishes the run: `completed` if `ok` is true, otherwise `failed`, or `cancelled` when the run was cancelled. |

5. If the stream ends without `run_finished`, the run finishes `failed` with "harness ended without a terminal event".

## Finishing (`_finish`)

- `completed`: writes a clean `Session` with `last_seen_seq = delta_end_seq`. It never uses the channel's current max seq, which would silently drop messages queued during the run.
- `failed` or `cancelled` after the run started: marks the session `dirty`, so the next turn rebuilds cold.
- In all cases it clears the partial, publishes the event, pumps the queue, and on completion considers a checkpoint.

## Errors (`lgt/run_errors.py`)

- `normalize_error` maps a raw error to `{code, message, exit_code, signal}`. Codes are `oom`, `orphaned`, `auth`, `timeout`, `signal`, `cancelled` and `harness`. An exit code of 137 alone is never treated as out of memory.
- `failure_text` builds a line such as "codex exited 137 (out of memory) after 2m 31s".
- `gateway._event_payload` also enriches older or terminal `run_status` events served over HTTP from the run row.

## Cancellation (`cancel_run`)

1. Adds the run to `_cancelled`.
2. Calls `runner.cancel()`: Codex interrupts the turn, and streaming runners terminate the process tree after `cancel_grace_seconds`.
3. Cancels the task and finishes the run as `cancelled` if it isn't terminal yet.

Removing a member, archiving a channel, retiring an agent and shutdown all go through `cancel_run`. The terminal payload doesn't record which of them caused the cancellation; see gap D5 in `design/backend-gaps.md`.

## Orphan recovery

`Orchestrator.start` handles runs that were still active when the previous backend stopped:
- On POSIX, it kills the run's surviving process group.
- On Windows, the Job Object has already ended the process tree; the backend never kills a stored pid, because the pid may have been reused.
- It then marks the run `failed` with error `orphaned`, dirties the session, and replays the durable queue.

## Related

- [Dispatch and queue](dispatch-and-queue.md) — how runs are created.
- [Harness adapters](harness-adapters.md) — the producers of `NormalizedEvent`.
- [Context and sessions](context-and-sessions.md) — what clean or dirty sessions mean.
- [Live state](live-state.md) — the `agent_status` and `usage` frames runs drive.
