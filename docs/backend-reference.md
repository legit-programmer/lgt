# Backend reference

The backend supports one local human, identified as `local`. HTTP and WebSocket clients connect through the same loopback origin. The command entry point binds to `127.0.0.1`, uses one Uvicorn worker, and disables proxy header trust. A file lock prevents a second orchestrator from opening the same data directory.

## Implemented behavior

| Component | Behavior |
| --- | --- |
| Store | Eight SQLite tables (including attachments), WAL, immutable events, per-channel sequence allocation, and a global replay cursor. |
| Orchestrator | One mailbox per channel, persistent dispatch queues, one active run per agent and channel, and a global run semaphore. |
| Router | `claude -p` with Haiku, then `codex exec --ephemeral`, then a random channel member. Each model call receives strict JSON routing instructions. |
| Codex adapter | Official SDK thread start or resume, streamed turn notifications, interruption, tool normalization, and per-turn token usage. |
| Context | Shared deterministic rendering for resume and cold rebuild, edits applied at the captured boundary, reset invalidation, and checkpoint summaries. |
| Gateway | HTTP configuration and scrollback, WebSocket cursor replay, live text deltas, partial snapshots, and replay overflow resync. |
| Process host | Per-run stderr logs, bounded stdout lines, Windows Job Objects, and POSIX process groups. |
| Checkpoints | Asynchronous rolling summaries through an injected summarizer. CLI generation is enabled only by explicit configuration. |

Unmentioned messages route immediately, including while agents are running. A router decision that selects a busy agent adds durable work to that agent's queue. Messages for the same busy agent coalesce into its next turn. The session advances to the captured `delta_end_seq` after the terminal event commits.

Every specialist turn uses bypassed permissions. The SDK receives `ApprovalMode.deny_all`, whose wire value is `approvalPolicy: never`, together with `Sandbox.full_access`. The Claude router and summarizer receive `--dangerously-skip-permissions`. Their Codex fallbacks receive `--dangerously-bypass-approvals-and-sandbox`.

Claude Code and opencode specialist adapters are deferred. A Codex tool allowlist has no enforced SDK equivalent in this milestone. Agent validation rejects a nonempty `allowed_tools` list while its policy remains undecided. An empty list leaves the SDK's tools available. No agents or models are seeded automatically.

## HTTP API

| Method | Path | Result |
| --- | --- | --- |
| GET | `/health` | Backend status. |
| GET, POST | `/agents` | List or create agent configuration. |
| GET, PUT | `/agents/{agent_id}` | Read or replace agent configuration. |
| GET, POST | `/channels` | List or create channels and DMs. |
| GET, POST | `/channels/{channel_id}/members` | Read members or add an agent. |
| GET | `/channels/{channel_id}/events` | Scrollback, with `before_seq`, `after_seq`, and `limit`. |
| GET | `/channels/{channel_id}/runs` | Runs in a channel. |
| GET | `/runs/{run_id}` | Run status and usage. |
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
| DELETE | `/attachments/{attachment_id}` | Discard an attachment that was never sent. |
| POST | `/channels/{channel_id}/new` | Reset context. |
| POST | `/channels/{channel_id}/archive` | Archive a channel without deleting its directory. |

`/docs` contains generated request schemas. Human messages accept `text`, optional `mentions` and optional `attachments` (attachment IDs). A message needs text, attachments or both. Mentions can contain agent IDs or handles. When the field is omitted, the backend extracts known `@handles` from the text. An explicit list controls dispatch. DMs always dispatch their single agent.

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

A deletion uses `deleted: true` in `edit_message`. Commands produce durable event frames. Errors produce an error frame. Text deltas are live only. A subscriber whose live buffer overflows receives `resync` and closes with code `1013`.

## Channel changes

**Working directory.** A channel's cwd can change only while none of its runs is active. The change appends a `cwd_changed` event with `cwd`, `previous_cwd` and `managed`. Sessions are keyed to the old cwd, so they fail resume validation and rebuild cold from the log. The rebuilt prompt states the new directory. The old directory stays on disk. This replaces the original spec's rule that cwd is immutable.

**Members.** Adding a new agent appends `member_added`. Removing an agent appends `member_removed`, cancels the agent's `awaiting_agent` deliveries, and cancels its active runs in that channel. The membership change commits first, so a cancelled run cannot dispatch more work to the removed agent. Routing results that arrive later ignore agents that are no longer members. A DM's agent cannot be removed; archive the DM instead. Both events render to agents as system lines.

**Queued deliveries.** `cancel_delivery` marks pending queue items `cancelled` and appends `delivery_cancelled` with `target_seq`, `agent_ids` and `retracted`. When no recipients are named, a pending routing decision is cancelled too, and its result is discarded if it arrives later. If no agent has received the local human's message, and none will, the message is also retracted. Retraction appends a `message_edit` with `deleted: true`, which removes the message from every agent's future context.

**Attachments.** Uploads are stored under `data_dir/attachments/<attachment_id>/` with a sanitized filename, size and SHA-256. They are never stored in the channel cwd. An upload that exceeds `attachment_max_bytes` returns `413 too_large` and leaves no file behind. An attachment belongs to one channel and binds to exactly one message. After it is sent, it can't be rebound or deleted, and database triggers enforce this. The message payload records `attachment_id`, `filename`, `media_type` and `size_bytes`. Context rendering lists each file with its current absolute path, so any agent can open it. The Codex adapter also passes the images attached to a run's triggering messages as `localImage` inputs.

## Configuration

`config.example.json` contains the proposed settings. `attachment_max_bytes` caps each upload. None of those numeric values is an implicit runtime default. `load_config` requires every `Settings` field except `route_after_active`, which is fixed to `false` by the user's routing override.

`data_dir` expands the home directory marker. A relative path resolves beside the configuration file. The directory holds `workspace.sqlite3`, `workspace.lock`, managed `workspaces`, uploaded `attachments`, and per-run `logs`.

`codex_bin` overrides the native CLI used by the SDK host and its probe. Its default is the runtime installed with the pinned SDK. `claude_command` and `codex_router_command` are argv arrays. A null Codex router command uses the bundled native CLI. Prompts travel on stdin without shell interpolation.

`checkpoint_mode` must be `cli` or `deferred`. The CLI summarizer uses the routing model, timeout, retry count, and CLI commands. The router timeout also bounds SDK initialization and thread or turn setup. It does not bound the duration of an active specialist turn.

The SDK dependency is pinned to `openai-codex==0.160.1`. The adapter uses the public SDK for JSON-RPC. Private SDK access is limited to the binary resolver and subprocess handle for process status and termination. The byte host forwards protocol traffic unchanged, caps lines, and records stderr.

The adapter records token usage. Codex app-server does not supply monetary usage through the notifications used here, so `cost_usd` remains zero rather than an estimated bill.

## Verification sources

The [official SDK getting-started guide](https://github.com/openai/codex/blob/main/sdk/python/docs/getting-started.md) documents installation, authentication reuse, async clients, and thread resume. The [SDK API reference](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md) documents streamed turn handles and interruption. The [app-server protocol documentation](https://learn.chatgpt.com/docs/app-server) describes JSON-RPC notifications and thread and turn methods.

Tests use controlled runners, recorded notification shapes, and a local app-server fixture through the actual official SDK. The suite does not make model calls. POSIX process group tests require a POSIX host.
