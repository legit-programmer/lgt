# Backend reference

The backend supports one human, identified as `local`, shared by multiple desktop and mobile clients. HTTP and WebSocket clients connect through the same origin or an explicitly configured origin. The command entry point binds to `settings.listen_host` (default `127.0.0.1`), uses one Uvicorn worker, and disables proxy header trust. A file lock prevents a second orchestrator from opening the same data directory.

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

Channels have one persistent primary agent shared by every channel participant. Unmentioned messages go directly to that primary, including after task completion and while it is busy. Fresh channels, channels whose primary is unavailable, and channels with independent user tasks active across multiple agents use the router. Routing remains immediate. A busy recipient gets durable queued work; messages with the same recipient and task owner coalesce into its next turn. Handoff requests get separate turns so acceptance cannot transfer other queued tasks. The session advances to the captured `delta_end_seq` after the terminal event commits.

Ownership changes only on explicit user selection, accepted handoff, or router assignment. A single mention selects that agent; for multiple explicit mentions, the last recipient is remembered as primary and all receive work. A router assignment remembers its first eligible recipient. While independent tasks overlap, `routing_mode` is `router`; when overlap ends, the remembered primary resumes regardless of completion order. Delegated runs and deliveries count toward their parent task owner, so internal collaboration alone does not activate router mode. Explicit mentions always bypass the router. All transitions commit through the channel mailbox, with version checks preventing delayed handoffs or router replies from superseding a newer selection.

The Codex SDK receives `ApprovalMode.deny_all`, whose wire value is `approvalPolicy: never`, together with `Sandbox.full_access`. Claude specialist agents with a tool allowlist receive `--tools`, `--allowedTools`, `--permission-mode dontAsk`, and an MCP deny rule. Other Claude agents bypass interactive permissions. Gemini agents use `--approval-mode yolo`. The Claude router and summarizer receive `--tools ""` and `--dangerously-skip-permissions`. Their Codex fallbacks receive `--dangerously-bypass-approvals-and-sandbox`.

Harness capabilities determine which settings the API accepts. Codex and Gemini report `allowed_tools: false`; a nonempty allowlist is rejected. Claude tool IDs must be a subset of its advertised tools. Custom commands declare their enforced capabilities in a probe. No agents are seeded automatically. Scheduled or event-triggered agent posts remain a product decision.

## Desktop daemon

The Tauri shell starts or reconnects to the backend before the initial workspace load. It launches `python -m lgt --config <absolute-path> --port 0 --daemon` as a detached process without a console. `--daemon` runs the server in the foreground internally; the launcher owns detachment.

After application startup and socket binding succeed, the server atomically writes `data_dir/daemon.json`:

```json
{"pid":1234,"port":49152,"api_version":1,"token":"<per-launch-secret>","started_at":"2026-10-10T00:00:00+00:00"}
```

The descriptor has owner-only access on POSIX and a protected owner-and-SYSTEM DACL on Windows. The shell verifies the application, API version, and PID with an authenticated health request before reusing it. The existing workspace lock remains authoritative for duplicate launches. Shutdown removes only the current daemon's descriptor, before releasing that lock.

In daemon mode, every HTTP request except an allowed CORS preflight requires `Authorization: Bearer <token>`. This includes health, attachments, and API documentation. The per-launch token is accepted only from a loopback peer; persistent paired-device credentials work locally and remotely when remote listening is enabled. Missing or invalid credentials return `401 unauthorized`. Origin checks still apply. The first WebSocket frame must include the token within five seconds; authentication failure closes the socket with code 1008 before replay or snapshots.

`POST /shutdown` requires the local launch token over loopback, returns `{"status":"stopping"}`, and requests graceful shutdown. The runtime stops active runs and closes SQLite. Closing the desktop window preserves the background server. The sidebar's **Quit Lgt** action shuts down the managed daemon and exits the shell. Paired and explicitly external clients do not shut down the backend.

Logs rotate at 5 MiB with three backups in `data_dir/logs/daemon.log`. Manual loopback startup without `--daemon` retains the unauthenticated local API; device administration and `/shutdown` return 404. Non-loopback startup automatically enables daemon mode. Constructing a remote gateway without daemon authentication is rejected.

## Device pairing and remote access

Remote access reuses the same gateway and orchestrator. The daemon establishes no outbound tunnel or relay. Clients need a route to the advertised origin, for example over a private VPN or an independently configured HTTPS reverse proxy. Browser origins must be explicitly allowed; pairing does not grant CORS access.

Configure these settings, then restart the daemon:

```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 8000,
  "advertised_url": "http://workspace-vpn-host:8000",
  "allowed_origins": ["http://tauri.localhost", "tauri://localhost", "http://localhost:1420"]
}
```

This is a fragment of the existing `settings` object. The advertised address must be reachable from the client; the wildcard listen address is not a destination. Use an encrypted network for HTTP, or an HTTPS endpoint. Only IPv4 loopback and wildcard listeners are supported, so local administration remains reachable at `127.0.0.1`. `--port` overrides the configured port. Choose a stable port for direct connections; an ephemeral port needs external routing that tracks it. HTTPS termination, VPN setup, router forwarding, and client scanning are separate from the daemon.

All `/devices` routes require the current daemon launch token and an actual loopback peer. Device tokens cannot administer devices even when used locally. Forwarding headers never authorize local administration. A local reverse proxy still presents a loopback peer, but a remote device's credential does not become an administrator credential.

`POST /devices` accepts `{"name":"iPhone"}` and returns `201` with `Cache-Control: no-store`:

```json
{
  "device": {
    "device_id": "<generated-id>", "name": "iPhone", "created_at": "<UTC timestamp>",
    "last_used_at": null, "revoked_at": null
  },
  "pairing": {
    "type": "lgt-device", "version": 1, "url": "http://workspace-vpn-host:8000",
    "device_id": "<generated-id>", "name": "iPhone", "token": "<device-credential>"
  }
}
```

Encode the `pairing` object as JSON in the QR code. The credential has the prefix `lgt_device_` followed by 43 base64url characters generated from 32 random bytes. The phone stores this payload in local storage. It verifies `GET /connection` using `Authorization: Bearer <device-credential>`; the response is `{"device_id":"<generated-id>","local_admin":false}`. The local launch token receives `{"device_id":null,"local_admin":true}`. Manual development mode reports `false`.

The QR grants access directly and is not single-use or expiring. The raw credential is returned once and only its SHA-256 hash is persisted in `devices`. Listing and renaming never expose it. A name is trimmed and must contain 1–100 printable characters. Missing remote-listening or advertised-address configuration returns `409 pairing_unavailable` without creating a device.

Every HTTP request, including media, sends the credential in the Authorization header. WebSockets send `{"last_id":0,"token":"<device-credential>"}` as the first frame. Credentials never go into URLs. Client implementations should disable redirects for authenticated fetches and send credentials only to the selected backend origin.

`GET /devices` returns public device records, including revoked ones. `PATCH /devices/{id}` accepts `{"name":"Work phone"}`. `POST /devices/{id}/revoke` returns the device with `revoked_at` set; repeating it is idempotent. Revocation immediately rejects subsequent HTTP requests and WebSocket handshakes and closes every existing socket for that device with code 1008, including idle sockets. Other devices stay connected. Previously accepted workspace actions and agent runs continue. Credentials and revocations survive restarts; `last_used_at` updates at most once per minute on authenticated HTTP requests and socket handshakes.

All devices act as the same workspace human. Read cursors, profile, agents, history, and channel state are shared, not per-device user accounts.

## HTTP API

| Method | Path | Result |
| --- | --- | --- |
| GET | `/health` | `{status: "ok", application: "lgt", api_version: 1, pid}`. |
| POST | `/shutdown` | Token-protected graceful shutdown in daemon mode. |
| GET | `/connection` | Authenticated device identity and local-administration capability. |
| GET, POST | `/devices` | Local administration: list devices or create a named credential and QR payload. |
| PATCH | `/devices/{device_id}` | Local administration: rename a connection. |
| POST | `/devices/{device_id}/revoke` | Local administration: revoke access and disconnect its sockets. |
| GET | `/harnesses` | Detected CLI paths, versions, auth state, capabilities, model choices, and tools. |
| POST | `/harnesses/scan` | Refresh CLI discovery. |
| POST | `/harnesses/custom/probe` | Probe custom `command` and optional `extra_args` argv before model and tool selection. |
| GET | `/harnesses/{harness}/limits` | Latest plan-limit snapshot, or null when unavailable. |
| GET, POST | `/agents` | List or create agent configuration. |
| GET | `/agents/status` | Agent state, active runs across channels, activity, and last failure. |
| GET, PUT | `/agents/{agent_id}` | Read or replace agent configuration. |
| POST, DELETE | `/agents/{agent_id}/retire`, `/agents/{agent_id}` | Soft retirement. The POST uses the `/retire` path; DELETE uses the agent path. |
| GET, POST | `/channels` | List or create channels and DMs. |
| PATCH | `/channels/{channel_id}` | Rename with `{"name": "..."}` or set automatic handoffs with `{"allow_handoff": false}`; either or both fields are allowed. |
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

Channels also persist `primary_agent_id` (nullable), `ownership_version` (monotonically increasing), and `allow_handoff` (defaults to true for new and existing channels). Summaries include backend-computed `routing_mode: "primary" | "router" | "dm"` and `active_task_agent_ids`, covering active runs and pending agent deliveries. `primary_agent_id` retains the last assignment even if that agent leaves or retires; such an unavailable primary uses router mode until the next assignment. These fields arrive through `channel_summary` frames and survive reconnects and restarts. DMs retain their single-recipient behavior. The desktop displays the current destination and a channel action to enable or disable ownership handoffs.

`GET /agents/status` returns `idle`, `working`, `queued`, or `failed`. An activity has `kind`, `summary`, and `since`. A terminal `run_status` includes `agent_id`, `started_at`, `ended_at`, and `duration_ms`. Failure errors contain `code`, `message`, `exit_code`, and `signal`. The server supplies the human-readable failure `text`.

Tool calls contain `tool_call_id`, normalized `tool`, `label`, `summary`, and `input`. Results contain `tool_call_id`, `is_error`, `exit_code`, `duration_ms`, `bytes`, `lines`, `truncated`, and `output`. Byte and line counts describe the full output before truncation.

Mention routing writes `method: "mention"`, `reason_code: "mention"`, and `reason: "explicit mentions"`. Direct primary delivery uses `method: "primary"` and `reason_code: "primary"`. The model router sees agents outside the channel and can return `suggested_agents`. Outside agents are suggestions only. Reason codes are `mention`, `primary`, `router`, `router_failed_random`, and `none`; random fallback selects only channel members.

Context reports `mode`, `start_seq`, `messages_in_context`, `context_tokens`, `model_context_window`, and `checkpoint_seq`. Usage and window fields are null when the harness has not reported them for the current context. A reset invalidates the previous context usage. Multi-agent channels require `agent_id` on this endpoint.

Run token counters are `tokens_in`, `tokens_out`, `tokens_cached_in`, `tokens_cache_creation`, `tokens_reasoning`, and `tokens_total`. `cost_usd` is absent from API responses. `/usage` returns rows with the group key (`agent`, `channel`, or `day`), `run_count`, and those token totals. Plan-limit snapshots are stored independently per harness.

## WebSocket frames

The socket path is `/ws`. In daemon mode the first client frame contains a cursor and launch or device token:

```json
{"last_id": 0, "token": "<launch-or-device-token>"}
```

Manual loopback mode omits `token` and sends only `last_id`.

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

**Agent transfers.** Every channel turn includes current ownership, handoff policy, member handles/IDs/descriptions, and the messages assigned to this turn in `<channel_routing>`. Agents use this complete message to transfer work through any harness:

````text
```lgt-transfer
{"mode":"handoff","target":"assistant","text":"Schedule the requested meeting tomorrow. Include the agreed participants."}
```
````

`mode: "delegation"` dispatches work while preserving ownership; ordinary agent `@mentions` also delegate. `mode: "handoff"` is available only to the current primary in `routing_mode: primary` when `allow_handoff` is true and its turn's ownership version is still current. The receiver's normalized `run_started` accepts the task for execution and atomically transfers ownership and activity attribution. A queued, cancelled, failed-before-start, or removed receiver does not acquire ownership. A newer selection, assignment, disabled policy, unavailable source, or router mode rejects the ownership transfer; already delivered work continues as delegation. Handoff control messages are parsed only from agent outputs and only when the complete text matches the control envelope. The stored message contains readable task text plus transfer metadata; quoted examples cannot change ownership. Invalid transfers fail the run, and transfers respect membership and the hop limit. Custom harnesses may send structured transfer metadata; see their [protocol](custom-harness.md).

The append-only log records `ownership_changed` with `primary_agent_id`, `previous_agent_id`, `primary_handle`, `reason` (`user_selection`, `accepted_handoff`, or `router_assignment`), and `ownership_version`. `agent_transfer` records `mode`, `status` (`requested`, `accepted`, or `rejected`), `source`, `targets`, `message_seq`, and optional explanatory `text`. Agent progress, completion, and delegation messages never change ownership.

Direct primary delivery writes `routing_decision` with `method: "primary"`, `reason_code: "primary"`, and `reason: "channel primary agent"`. Mention and model-router payloads retain their existing fields. Run and queue persistence includes `task_owner_id`; run responses also expose the ownership version captured for the turn. These are task attribution fields; the channel summary remains authoritative for the current destination.

**Working directory.** A channel's cwd can change only while none of its runs is active. The change appends a `cwd_changed` event with `cwd`, `previous_cwd` and `managed`. Sessions are keyed to the old cwd, so they fail resume validation and rebuild cold from the log. The rebuilt prompt states the new directory. The old directory stays on disk. This replaces the original spec's rule that cwd is immutable.

**Members.** Adding a new agent appends `member_added`. Removing an agent appends `member_removed`, cancels the agent's `awaiting_agent` deliveries, and cancels its active runs in that channel. The membership change commits first, so a cancelled run cannot dispatch more work to the removed agent. Routing results that arrive later ignore agents that are no longer members. A DM's agent cannot be removed; archive the DM instead. Both events render to agents as system lines.

**Queued deliveries.** `cancel_delivery` marks pending queue items `cancelled` and appends `delivery_cancelled` with `target_seq`, `agent_ids` and `retracted`. When no recipients are named, a pending routing decision is cancelled too, and its result is discarded if it arrives later. If no agent has received the local human's message, and none will, the message is also retracted. Retraction appends a `message_edit` with `deleted: true`, which removes the message from every agent's future context.

**Attachments.** Uploads are stored under `data_dir/attachments/<attachment_id>/` with a sanitized filename, size and SHA-256. They are never stored in the channel cwd. An upload that exceeds `attachment_max_bytes` returns `413 too_large` and leaves no file behind. An attachment belongs to one channel and binds to exactly one message. After it is sent, it can't be rebound or deleted, and database triggers enforce this. The message payload records `attachment_id`, `filename`, `media_type` and `size_bytes`. Context rendering lists each file with its current absolute path, so any agent can open it. Codex also passes images as `localImage` inputs. Claude passes images and PDFs as native content blocks through streaming stdin. Custom harnesses receive file paths and metadata in their turn request.

## Configuration

`config.example.json` contains the settings. The original numeric runtime settings remain required. `route_after_active` is fixed to `false` by the user's routing override. New settings have defaults: `allowed_origins: []`, `attachment_channel_quota_bytes: 262144000`, `attachment_retention_seconds: 86400`, `thumbnail_max_dimension: 512`, `listen_host: "127.0.0.1"`, `listen_port: 8000`, and `advertised_url: null`.

`allowed_origins` contains exact origins without paths, credentials, queries, or fragments. It can include `tauri://localhost`, a development HTTP origin, or the literal `file://`. Wildcards and opaque `null` origins are rejected. Loopback client and Host checks apply only when remote listening is disabled. Remote mode accepts authenticated peers without subnet restrictions. Allowed HTTP origins receive CORS headers; preflight permits the API methods, `Content-Type`, and `Authorization`.

`listen_host` accepts `127.0.0.1` or `0.0.0.0`; `listen_port` is an integer from 0 through 65535. `advertised_url` is a reachable HTTP(S) origin without credentials, paths, query strings, or fragments, and cannot be a wildcard address or port zero.

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
