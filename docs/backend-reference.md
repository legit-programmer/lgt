# Backend reference

The backend supports one local human, identified as `local`. HTTP and WebSocket clients connect through the same loopback origin or an explicitly configured origin. The command entry point binds to `127.0.0.1`, uses one Uvicorn worker, and disables proxy header trust. A file lock prevents a second orchestrator from opening the same data directory.

## Implemented behavior

| Component | Behavior |
| --- | --- |
| Store | SQLite with additive migrations, WAL, immutable events, per-channel sequence allocation, read cursors, FTS5 search, and a global replay cursor. |
| Orchestrator | One mailbox per channel, persistent dispatch queues, one active run per agent and channel, and a global run semaphore. |
| Router | `claude -p` with Haiku, then `codex exec --ephemeral`, then a random channel member. Each model call receives strict JSON routing instructions. |
| Codex adapter | Official SDK thread start or resume, streamed turn notifications, interruption, tool normalization, and per-turn token usage. |
| CLI adapters | Claude Code and Gemini NDJSON streams, resume, process interruption, tools, and token usage. Custom commands use the [stdio protocol](custom-harness.md). |
| Context | Shared deterministic rendering for resume and cold rebuild, edits applied at the captured boundary, reset invalidation, and checkpoint summaries. |
| Gateway | HTTP configuration and scrollback, WebSocket cursor replay, live text deltas, partial snapshots, and replay overflow resync. |
| Process host | Per-run stderr logs, bounded stdout lines, Windows Job Objects, and POSIX process groups. |
| Checkpoints | Asynchronous rolling summaries through an injected summarizer. CLI generation is enabled only by explicit configuration. |

Unmentioned messages route immediately, including while agents are running. A router decision that selects a busy agent adds durable work to that agent's queue. Messages for the same busy agent coalesce into its next turn. The session advances to the captured `delta_end_seq` after the terminal event commits.

The Codex SDK receives `ApprovalMode.deny_all`, whose wire value is `approvalPolicy: never`, together with `Sandbox.full_access`. Claude specialist agents with a tool allowlist receive `--tools`, `--allowedTools`, `--permission-mode dontAsk`, and an MCP deny rule. Other Claude agents bypass interactive permissions. Gemini agents use `--approval-mode yolo`. The Claude router and summarizer receive `--tools ""` and `--dangerously-skip-permissions`. Their Codex fallbacks receive `--dangerously-bypass-approvals-and-sandbox`.

Harness capabilities determine which settings the API accepts. Codex and Gemini report `allowed_tools: false`; a nonempty allowlist is rejected. Claude tool IDs must be a subset of its advertised tools. Custom commands declare their enforced capabilities in a probe. No agents are seeded automatically. Scheduled or event-triggered agent posts remain a product decision.

## HTTP API

| Method | Path | Result |
| --- | --- | --- |
| GET | `/health` | Backend status. |
| GET | `/harnesses` | Detected CLI paths, versions, auth state, capabilities, model choices, and tools. |
| POST | `/harnesses/scan` | Refresh CLI discovery. |
| POST | `/harnesses/custom/probe` | Probe custom `command` and optional `extra_args` argv before model and tool selection. |
| GET | `/harnesses/{harness}/limits` | Latest plan-limit snapshot, or null when unavailable. |
| GET, POST | `/agents` | List or create agent configuration. |
| GET | `/agents/status` | Agent state, active runs across channels, activity, and last failure. |
| GET, PUT | `/agents/{agent_id}` | Read or replace agent configuration. |
| POST, DELETE | `/agents/{agent_id}/retire`, `/agents/{agent_id}` | Soft retirement. The POST uses the `/retire` path; DELETE uses the agent path. |
| GET, POST | `/channels` | List or create channels and DMs. |
| PATCH | `/channels/{channel_id}` | Rename a channel with `{"name": "..."}`. |
| POST | `/channels/{channel_id}/unarchive` | Restore an archived channel. A retired agent's DM stays archived. |
| POST | `/channels/{channel_id}/read` | Advance the server read cursor with `{"seq": 12}`. |
| GET | `/channels/{channel_id}/context?agent_id=` | Session mode, message count, reported context tokens, window size, and checkpoint. |
| GET | `/channels/{channel_id}/suggestions` | Three starter prompts generated with the router model, cached per roster. |
| GET, POST | `/channels/{channel_id}/members` | Read members or add an agent. |
| GET | `/channels/{channel_id}/events` | Scrollback, with `before_seq`, `after_seq`, and `limit`. |
| GET | `/channels/{channel_id}/runs` | Runs in a channel. |
| GET | `/runs/{run_id}` | Run status and usage. |
| GET | `/runs?agent_id=&channel_id=&status=&limit=` | Recent runs. Status is `active` or `terminal`; limit defaults to 100 and is capped at 500. |
| GET | `/runs/{run_id}/log?tail=` | Last stderr lines. Tail defaults to 200 and is capped at 10000. |
| GET | `/usage?group_by=&since=` | Token totals by `agent`, `channel`, or `day`. Since accepts an ISO date or timestamp. |
| GET | `/search?q=&channel_id=&kinds=` | Matching channels, agents, and messages with sequence anchors. Kinds is a comma-separated filter. |
| GET | `/commands` | Server command registry: `/new`, `/cwd`, and `/cancel`. |
| GET | `/templates` | Starter presets filtered by detected harnesses, models, and tools. |
| POST | `/bootstrap` | Atomically create `agent_templates` and #general in the supplied existing `cwd`. |
| GET, PATCH | `/me` | Persistent local display name. PATCH accepts `{"display_name": "..."}`. |
| POST | `/runs/{run_id}/cancel` | Cancel a run. |
| POST | `/channels/{channel_id}/messages` | Append a human message and dispatch or queue work. |
| PATCH | `/channels/{channel_id}/messages/{seq}` | Append an edit or deletion event. |
| DELETE | `/channels/{channel_id}/members/{agent_id}` | Remove an agent, cancel its pending deliveries and active runs in the channel. |
| PUT | `/channels/{channel_id}/cwd` | Move the channel to an existing absolute directory, or `{"cwd": null}` for its managed directory. |
| GET | `/channels/{channel_id}/queue` | Pending deliveries: messages awaiting routing or a busy agent. |
| POST | `/channels/{channel_id}/messages/{seq}/cancel` | Cancel a message's pending deliveries, optionally `{"agent_ids": [...]}`. |
| POST | `/channels/{channel_id}/attachments?filename=` | Upload one file as the raw body. `Content-Type` is its media type. |
| GET | `/attachments/{attachment_id}` | Download a file. Only PNG, JPEG, GIF and WebP are served inline. |
| GET | `/attachments/{attachment_id}/meta` | Attachment metadata. |
| GET | `/attachments/{attachment_id}/thumbnail` | A bounded JPEG thumbnail for supported image uploads. |
| DELETE | `/attachments/{attachment_id}` | Discard an attachment that was never sent. |
| POST | `/channels/{channel_id}/new` | Reset context. |
| POST | `/channels/{channel_id}/archive` | Archive a channel without deleting its directory. |

`/docs` contains generated request schemas. Human messages accept `text`, optional `mentions` and optional `attachments` (attachment IDs). A message needs text, attachments or both. Mentions can contain agent IDs or handles. When the field is omitted, the backend extracts known `@handles` from the text. An explicit list controls dispatch. DMs always dispatch their single agent.

## Agent identity and harness choices

`POST /agents` accepts an optional `agent_id`. Omitting it generates a ULID. The response includes `avatar`, `hue`, and `dm_channel_id`. The avatar defaults to `{"style": "critters", "seed": agent_id}` (DiceBear Critters, CC0). Databases from before this default switch their default `bottts` avatars to `critters` once, on first open. Hue is a fixed index from 0 through 7, assigned in creation order to violet, sky, pink, green, lime, plum, indigo, and sand. Renaming preserves identity and the DM.

`model` must match an advertised harness model ID. `claude_code` is an alias for `claude`. `command` is an argv array for custom agents. `extra_args` accepts only flags that the adapter validates; protocol, model, and tool-policy overrides are rejected. A retirement sets `retired_at`, removes channel memberships, cancels deliveries and runs, and archives the DM. Historical runs and events retain their agent references.

The harness catalog reports `resume`, `interrupt`, `text_delta`, `allowed_tools`, `image_input`, `usage`, and `rate_limits`. Auth can be `signed_in`, `signed_out`, or `unknown`. Unknown means that discovery has no reliable read-only auth result. Missing CLIs appear with `found: false`.

## Sidebar, context, and usage

`GET /channels` returns each channel with `members`, `last_activity_at`, a `preview`, `unread_count`, and `active_runs`. The preview contains `seq`, `kind`, `author_id`, and `text_excerpt`. Edits change previews and search hits; deletions hide the original text. Unread counts include agent messages after the local read cursor. Read cursors advance monotonically and survive restarts.

`GET /agents/status` returns `idle`, `working`, `queued`, or `failed`. An activity has `kind`, `summary`, and `since`. A terminal `run_status` includes `agent_id`, `started_at`, `ended_at`, and `duration_ms`. Failure errors contain `code`, `message`, `exit_code`, and `signal`. The server supplies the human-readable failure `text`.

Tool calls contain `tool_call_id`, normalized `tool`, `label`, `summary`, and `input`. Results contain `tool_call_id`, `is_error`, `exit_code`, `duration_ms`, `bytes`, `lines`, `truncated`, and `output`. Byte and line counts describe the full output before truncation.

Mention routing writes `method: "mention"`, `reason_code: "mention"`, and `reason: "explicit mentions"`. The model router sees agents outside the channel and can return `suggested_agents`. Outside agents are suggestions only. Reason codes are `mention`, `router`, `router_failed_random`, and `none`; random fallback selects only channel members.

Context reports `mode`, `start_seq`, `messages_in_context`, `context_tokens`, `model_context_window`, and `checkpoint_seq`. Usage and window fields are null when the harness has not reported them for the current context. A reset invalidates the previous context usage. Multi-agent channels require `agent_id` on this endpoint.

Run token counters are `tokens_in`, `tokens_out`, `tokens_cached_in`, `tokens_cache_creation`, `tokens_reasoning`, and `tokens_total`. `cost_usd` is absent from API responses. `/usage` returns rows with the group key (`agent`, `channel`, or `day`), `run_count`, and those token totals. Plan-limit snapshots are stored independently per harness.

## WebSocket frames

The socket path is `/ws`. The first client frame is a cursor:

```json
{"last_id": 0}
```

The server captures replay rows and partial snapshots before sending frames. Durable events have this envelope:

```json
{"type": "event", "event": {"id": 1, "channel_id": "...", "seq": 1, "kind": "message", "payload": {"text": "hello", "mentions": []}}}
```

The event object also includes its timestamp, author, run, chain, and hop fields. Agent payloads capture `author_handle` so an agent rename does not change an existing prompt's rendered author labels. Other server frames are:

```json
{"type": "delta", "run_id": "...", "channel_id": "...", "text": "chunk"}
{"type": "partial_snapshot", "run_id": "...", "channel_id": "...", "text": "partial response"}
{"type": "queue", "channel_id": "...", "items": [{"queue_id": 1, "event_seq": 4, "agent_id": "...", "state": "awaiting_agent", "created_at": "..."}]}
{"type": "resync", "channels": ["..."]}
{"type": "error", "error": {"code": "invalid_command", "message": "..."}}
```

Client commands use a `type` field:

```json
{"type": "send_message", "channel_id": "...", "text": "hello", "mentions": ["agent_id"], "attachments": ["attachment_id"]}
{"type": "edit_message", "channel_id": "...", "target_seq": 1, "text": "updated"}
{"type": "cancel_run", "run_id": "..."}
{"type": "new_context", "channel_id": "..."}
{"type": "cancel_delivery", "channel_id": "...", "target_seq": 4, "agent_ids": ["agent_id"]}
```

A `queue` frame carries a channel's full list of pending deliveries whenever it changes. An empty list means nothing is pending. After the cursor replay, the socket sends one `queue` frame for each channel with pending deliveries. Items in `awaiting_route` have a null `agent_id`.

After replay, the server sends current `channel_summary`, `agent_status`, `context`, `usage`, available `harness_limits`, and `me` frames. These snapshots are captured before replay is sent. Live changes use the same frame types. `channel_summary`, `agent_status`, and `context` flatten their HTTP object into the frame beside `type`. A `usage` frame carries a run's token counters or grouped `totals`; a limits update includes `harness` and `limits`. An `agent` frame announces creation, configuration changes, or retirement. Global agent, usage-limit, and profile updates reach every connected window.

A deletion uses `deleted: true` in `edit_message`. Commands produce durable event frames. Errors produce an error frame. Text deltas are live only. A subscriber whose live buffer overflows receives `resync` and closes with code `1013`.

## Channel changes

**Working directory.** A channel's cwd can change only while none of its runs is active. The change appends a `cwd_changed` event with `cwd`, `previous_cwd` and `managed`. Sessions are keyed to the old cwd, so they fail resume validation and rebuild cold from the log. The rebuilt prompt states the new directory. The old directory stays on disk. This replaces the original spec's rule that cwd is immutable.

**Members.** Adding a new agent appends `member_added`. Removing an agent appends `member_removed`, cancels the agent's `awaiting_agent` deliveries, and cancels its active runs in that channel. The membership change commits first, so a cancelled run cannot dispatch more work to the removed agent. Routing results that arrive later ignore agents that are no longer members. A DM's agent cannot be removed; archive the DM instead. Both events render to agents as system lines.

**Queued deliveries.** `cancel_delivery` marks pending queue items `cancelled` and appends `delivery_cancelled` with `target_seq`, `agent_ids` and `retracted`. When no recipients are named, a pending routing decision is cancelled too, and its result is discarded if it arrives later. If no agent has received the local human's message, and none will, the message is also retracted. Retraction appends a `message_edit` with `deleted: true`, which removes the message from every agent's future context.

**Attachments.** Uploads are stored under `data_dir/attachments/<attachment_id>/` with a sanitized filename, size and SHA-256. They are never stored in the channel cwd. An upload that exceeds `attachment_max_bytes` returns `413 too_large` and leaves no file behind. An attachment belongs to one channel and binds to exactly one message. After it is sent, it can't be rebound or deleted, and database triggers enforce this. The message payload records `attachment_id`, `filename`, `media_type` and `size_bytes`. Context rendering lists each file with its current absolute path, so any agent can open it. Codex also passes images as `localImage` inputs. Claude passes images and PDFs as native content blocks through streaming stdin. Custom harnesses receive file paths and metadata in their turn request.

## Configuration

`config.example.json` contains the settings. The original numeric runtime settings remain required. `route_after_active` is fixed to `false` by the user's routing override. New settings have defaults: `allowed_origins: []`, `attachment_channel_quota_bytes: 262144000`, `attachment_retention_seconds: 86400`, and `thumbnail_max_dimension: 512`.

`allowed_origins` contains exact origins without paths, credentials, queries, or fragments. It can include `tauri://localhost`, a development HTTP origin, or the literal `file://`. Wildcards and opaque `null` origins are rejected. Loopback client and Host checks still apply to HTTP and WebSockets. Allowed HTTP origins receive CORS headers; preflight permits the API methods and `Content-Type`.

`attachment_max_bytes` caps each upload; the channel quota counts sent and unsent files. Concurrent uploads share the same quota check. Unsent uploads expire after the retention window. Cleanup runs at startup and periodically. Sent files stay immutable. Thumbnails reject invalid images and excessive dimensions.

`data_dir` expands the home directory marker. A relative path resolves beside the configuration file. The directory holds `workspace.sqlite3`, `workspace.lock`, managed `workspaces`, uploaded `attachments`, and per-run `logs`.

`codex_bin` overrides the native CLI used by the SDK host and its probe. Its default is the runtime installed with the pinned SDK. `claude_command`, `gemini_command`, and `codex_router_command` are argv arrays. A null Codex router command uses the bundled native CLI. Commands launch without shell interpolation.

`checkpoint_mode` must be `cli` or `deferred`. The CLI summarizer uses the routing model, timeout, retry count, and CLI commands. The router timeout also bounds SDK initialization and thread or turn setup. It does not bound the duration of an active specialist turn.

The SDK dependency is pinned to `openai-codex==0.160.1`. The adapter uses the public SDK for JSON-RPC. Private SDK access is limited to the binary resolver and subprocess handle for process status and termination. The byte host forwards protocol traffic unchanged, caps lines, and records stderr.

The adapter records token usage and available rate-limit windows. Unsupported plan usage stays unavailable rather than becoming an estimated bill.

## Verification sources

The [official SDK getting-started guide](https://github.com/openai/codex/blob/main/sdk/python/docs/getting-started.md) documents installation, authentication reuse, async clients, and thread resume. The [SDK API reference](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md) documents streamed turn handles and interruption. The [app-server protocol documentation](https://learn.chatgpt.com/docs/app-server) describes JSON-RPC notifications and thread and turn methods.

Tests use controlled runners, recorded notification shapes, and a local app-server fixture through the actual official SDK. The suite does not make model calls. POSIX process group tests require a POSIX host.

The [Claude CLI reference](https://code.claude.com/docs/en/cli-reference) documents print mode, streaming, resume, and tool settings. The [Claude streaming input guide](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode) documents native image content blocks. The [Gemini headless reference](https://geminicli.com/docs/cli/headless/) documents NDJSON events and terminal exit codes.
