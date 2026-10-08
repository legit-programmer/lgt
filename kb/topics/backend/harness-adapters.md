---
id: 20261008-harness-adapters
title: Harness adapters
tags: [backend, harness]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-run-lifecycle, 20261008-process-hosting, 20261008-full-permission-agents, 20261008-open-gaps]
summary: The harness registry (discovery, catalogs, capability-based validation, runner factory) and the Codex, Claude, Gemini, and custom adapters that turn CLI output into normalized events.
---

# Harness adapters

> Summary: The harness registry (discovery, catalogs, capability-based validation, runner factory) and the Codex, Claude, Gemini, and custom adapters that turn CLI output into normalized events.

## Registry (`lgt/harnesses.py`)

`HarnessRegistry` holds one catalog entry per harness: `harness`, `found`, `path`, `version`, `auth`, `capabilities`, `models` and `tools`. `GET /harnesses` serves this catalog.

- **`scan()`** (`POST /harnesses/scan`) runs the following checks:
  - `--version` on each CLI;
  - `claude auth status` for Claude's sign-in state;
  - for Codex, `client.models()` and `client.account()` through the SDK;
  - `--help` checks that confirm the Claude and Gemini capability flags.
  - Gemini auth stays `unknown`, because it has no read-only check.
- **`probe_custom(command, extra_args)`** runs `<argv> --lgt-probe` and validates the descriptor in [docs/custom-harness.md](../../../docs/custom-harness.md). The result is cached per argv.
- **`validate_agent(agent)`** is called from `Orchestrator.put_agent`. It rejects:
  - an unknown or uninstalled harness;
  - a model not in the catalog;
  - `allowed_tools` when the harness can't enforce them, or tools outside its catalog;
  - unsafe `extra_args`. Claude allows only `--max-turns N` and `--max-budget-usd X`; custom harnesses reject `--lgt-*` flags.
- **`runner(harness)`** is the orchestrator's runner factory. **`artifact_exists`** checks that a stored session can still be resumed.

## Adapters

| Harness | File | How it runs |
| --- | --- | --- |
| `codex` | `lgt/codex_adapter.py` (`CodexAppServerRunner`) | Official `openai-codex` SDK (pinned `0.160.1`) driving `codex app-server` through `sdk_host.py`. Starts or resumes a thread and streams turn notifications. Images go in as `LocalImageInput`. Reports token usage and `account/rateLimits/updated` limits. |
| `claude` | `lgt/streaming_adapter.py` (`ClaudeRunner`) | `claude -p --output-format stream-json --verbose --include-partial-messages --input-format stream-json --model … --append-system-prompt …`. The prompt, images and PDFs go to stdin as stream-json content blocks. `--resume <session>` when resuming. |
| `gemini` | `streaming_adapter.py` (`GeminiRunner`) | Gemini headless NDJSON with `--approval-mode yolo`. No tool allowlist and no image input. |
| `custom` | `streaming_adapter.py` (`CustomRunner`) | The agent's `command` argv. Receives one JSON turn request on stdin and emits protocol v1 events. Always runs cold. |

`StreamingRunner` handles everything shared by the NDJSON adapters:
- spawning through `processes.spawn_command` in the channel cwd;
- bounded stdout lines (`ndjson_line_limit`);
- the stderr log file;
- terminating the process tree on cancel;
- the rule that a run fails without a terminal event or with a nonzero exit.

## Normalized events

Each adapter yields `NormalizedEvent(kind, data)` with these kinds:

- `process_started`, `run_started`
- `text_delta`, `message`
- `tool_call`: `tool_call_id`, `tool`, `label`, `summary`, `input`
- `tool_result`: `tool_call_id`, `is_error`, `exit_code`, `duration_ms`, `bytes`, `lines`, `truncated`, `output`
- `usage`: increments, or `cumulative` totals, of `tokens_in`, `tokens_out`, `tokens_cached_in`, `tokens_cache_creation`, `tokens_reasoning` and `tokens_total`, plus `context_tokens` and `model_context_window`
- `limits`
- `run_finished`

`bytes` and `lines` describe the full output before truncation to `tool_output_cap`.

## Known adapter gaps

- Claude tool results have `duration_ms: null`.
- Tool `summary` strings use absolute paths.

Both are tracked as D3 and D4 in [open gaps](../status/open-gaps.md).

## Related

- [Run lifecycle](run-lifecycle.md) — how normalized events are consumed.
- [Process hosting](process-hosting.md) — spawning and killing process trees.
- [Full-permission agents](../decisions/full-permission-agents.md) — why runs bypass approvals.
- [Open gaps](../status/open-gaps.md) — remaining adapter work.
