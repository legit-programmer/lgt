# Backend gaps for the Lgt screens

The contracts below are implemented. The original gap descriptions are retained as the acceptance checklist. See the [backend reference](../docs/backend-reference.md) and [custom harness protocol](../docs/custom-harness.md) for the current API.

Capabilities remain explicit: unsupported tool policies, resume, native inputs, or plan-limit reporting are advertised as unavailable. Agent settings are validated against those capabilities and the harness model and tool catalogs. Custom argv commands have a separate probe endpoint for their catalogs.

The remaining product decision is proactive scheduled or event-triggered agent posts. Voice input and theme changes remain frontend work.

This compares `Lgt Screens.pdf` with the backend as of 2026-10-08. Each gap is a backend contract to build. The frontend does not compensate for missing backend features. It does not scan every channel to derive status, keep state in localStorage that the server should own, or guess queue state from heuristics. Any state the UI shows comes from the backend through HTTP for the initial load and WebSocket frames for changes.

## Closed in this change

| UI element | Backend contract | Reference |
| --- | --- | --- |
| Change working directory | `PUT /channels/{id}/cwd`, `cwd_changed` event, cold rebuild of affected sessions | [backend reference](../docs/backend-reference.md#channel-changes) |
| Remove an agent from a channel (× in the detail panel) | `DELETE /channels/{id}/members/{agent_id}`, `member_removed` / `member_added` events | same |
| Queued message, "sends when it's free", Cancel | `GET /channels/{id}/queue`, live `queue` frame, `POST /channels/{id}/messages/{seq}/cancel`, `cancel_delivery` WS command, `delivery_cancelled` event | same |
| Attachments (paperclip button) | `POST /channels/{id}/attachments`, `GET`/`DELETE /attachments/{id}`, `attachments` on messages, images passed to Codex as native inputs | same |

## P0: the screens can't work without these

### 1. Harness adapters beyond Codex

The screens back coder, planner and docs with `claude`, and offer `gemini` and a custom stdio command. Today `put_agent` rejects any harness except `codex`, and `runner_factory` builds only Codex runners.

Needed:

- **Claude Code adapter.** `claude -p --output-format stream-json`, with session resume through `--resume`, interrupt, and tool and usage normalization. It should also implement `artifact_exists`.
- **Gemini adapter** with the same contract.
- **`custom` harness.** An agent-defined argv that follows a documented NDJSON protocol for messages, tool calls, usage and the terminal event.
- **A probe for each adapter** that reports which capabilities it supports: `resume`, `interrupt`, `text_delta`, `allowed_tools`, `image_input`, `usage`, `rate_limits`. The API must reject agent settings that the chosen harness doesn't support.

### 2. Harness discovery

These drive the New agent "Backing CLI" cards and onboarding step 1 ("CLIs found on this machine", "Scan again", detected / missing / install, signed in).

```
GET  /harnesses            -> [{harness, found, path, version, auth: "signed_in"|"signed_out"|"unknown",
                                capabilities, models: [{id, label, description, default}],
                                tools: [{id, label, description}]}]
POST /harnesses/scan       -> same, re-probed
```

The model list replaces the free-text `model` field and supplies the helper text ("Sonnet is the default balance of speed and depth."). Agent validation checks `model` against the harness's model list.

### 3. Tool access

The "Tool access" control and the tool sets on agent cards ("Read · Grep · Edit · Bash") need tool allowlists that the backend actually enforces. Today any non-empty `allowed_tools` is rejected.

Needed:

- **A tool list per harness**, served by `GET /harnesses`.
- **Enforcement in each adapter.** For example, Claude takes `--allowedTools`. If Codex has no equivalent, Codex reports `allowed_tools: false` and the API rejects the setting for Codex agents.
- **Validation:** the agent's tools must be a subset of its harness's tools.

### 4. Origin for the desktop shell

The gateway accepts only same-origin loopback requests. A Tauri or Electron origin (`tauri://localhost`, `file://`) or a dev server on another port gets a 403. Pick one:

- serve the built frontend from the backend's own origin, or
- add an explicit `allowed_origins` setting, checked as strictly as today's same-origin rule.

## P1: data the screens display

### 5. Agent identity and lifecycle

| Field / route | Purpose |
| --- | --- |
| `avatar: {style, seed}` | The chosen DiceBear avatar. The seed defaults to `agent_id`, so renaming an agent keeps its face. |
| `hue` | Assigned by the server in creation order from the eight agent hues and fixed for life. The client never computes it. |
| `extra_args: list[str]` | "Extra CLI flags", validated per harness and passed to every run. |
| Server-generated `agent_id` | `POST /agents` should not require the client to choose an ID. |
| `POST /agents/{id}/retire` (or `DELETE`) | Removes an agent from the roster. Runs and events reference agents with `RESTRICT` foreign keys, so this should be a soft retirement with `retired_at`. |
| `dm_channel_id` on the agent | A DM channel created automatically with the agent, so "IN THE SIDEBAR" works from the moment it's created. |

### 6. Sidebar summaries and read state

Today `GET /channels` returns bare rows.

```
GET /channels -> [{...channel, members, last_activity_at,
                   preview: {seq, kind, author_id, text_excerpt},
                   unread_count, active_runs: [{run_id, agent_id, status, started_at}]}]
POST /channels/{id}/read {seq}              # read cursor stored by the server
WS {"type": "channel_summary", "channel_id": ..., ...same shape}   # on every change
```

Read cursors live in a new `read_cursors` table, so unread markers are the same in every window.

### 7. Agent status across channels

These drive the footer ("5 AGENTS · 2 WORKING"), each agent row's status dot and activity line ("Running pnpm lint…", "Writing PR note…"), and "Runs · 2 running".

```
GET /agents/status -> [{agent_id, state: "idle"|"working"|"queued"|"failed",
                        active_runs: [{run_id, channel_id, started_at}],
                        activity: {kind: "tool"|"writing", summary, since} | null,
                        last_failure: {run_id, error, at} | null}]
WS {"type": "agent_status", ...same shape}
GET /runs?agent_id=&channel_id=&status=active|terminal&limit=
```

### 8. Richer run lifecycle events

`run_status` payloads carry only `run_id` and `status`. Add `agent_id`, `started_at`, `ended_at` and `duration_ms`. Failures also need a structured `error`: `{code: "oom"|"signal"|"auth"|"timeout"|"harness"|..., message, exit_code, signal}`. The backend writes the human-readable failure text ("codex exited 137 (out of memory) after 2m 31s") from that record, not the client.

### 9. Normalized tool events

Codex emits raw item types (`commandExecution`, `fileChange`). The tool rows show Bash, Read, Edit and Grep with a one-line target. Each adapter should normalize to:

```
tool_call   {tool_call_id, tool: "bash"|"read"|"edit"|"grep"|"web_fetch"|..., label, summary, input}
tool_result {tool_call_id, is_error, exit_code, duration_ms, bytes, lines, truncated, output}
```

`summary` is the row text, e.g. "playwright.config.ts workers: 8 → 4". Line count is measured before truncation, because only the backend sees the full output.

### 10. Routing explanations

- **Mention routing has no record.** Explicit mentions skip the router and write no `routing_decision`. Record one with `method: "mention"` and `reason: "explicit mentions"`.
- **"No agent here" should suggest one.** Let the router see agents outside the channel and return `suggested_agents` with "routed → none". This produces the hint "add shell-ops to this channel".
- **Reason codes.** Add `reason_code` (`mention`, `router`, `router_failed_random`, `none`) next to the free-text reason.

### 11. Context stats

These drive the DM header ("6 messages in context · 12.4k tokens").

```
GET /channels/{id}/context?agent_id= -> {mode: "resume"|"cold", start_seq, messages_in_context,
                                          context_tokens, model_context_window, checkpoint_seq}
```

`context_tokens` comes from the harness's last reported usage. Codex reports `model_context_window` in `thread/tokenUsage/updated`. Push changes with a `context` WS frame after each run and each reset.

### 12. Usage instead of cost

The UI does not show currency. Remove `cost_usd` from the API. Adapters report token usage and the harness's own plan usage.

| Source | Codex | Claude Code |
| --- | --- | --- |
| Tokens per turn | `thread/tokenUsage/updated`: input, cached input, output, reasoning, total. The adapter currently keeps only input and output. | `result` event `usage`: input, output, cache read, cache creation |
| Plan / limit usage | `account/rateLimits/updated` notification: primary and secondary windows with `usedPercent`, `windowDurationMins`, `resetsAt`, plus `planType` | Check what `stream-json` exposes for rate limits in the pinned CLI version before relying on it |

Needed:

- **Run columns:** `tokens_cached_in`, `tokens_reasoning`, `tokens_total`.
- **A `harness_limits` table** with the latest snapshot per harness.
- **Endpoints:**

  ```
  GET /usage?group_by=agent|channel|day&since=   -> token totals
  GET /harnesses/{harness}/limits                -> latest window snapshot
  WS {"type": "usage", ...}                      -> on each update
  ```

## P2: remaining controls

| Gap | Contract |
| --- | --- |
| Search: ⌘K "Search or jump to…" and search within a channel | SQLite FTS5 over message text and tool summaries. `GET /search?q=&channel_id=&kinds=` returns channels, agents and message hits with seq anchors. |
| Run tab: logs | `GET /runs/{id}/log?tail=` for the per-run stderr log that already exists on disk. |
| Slash commands ("/ for commands") | `GET /commands` returns the server-side registry (`/new`, `/cwd`, `/cancel` …). Commands run on the server, as `/new` does today. |
| Channel management | Rename (`PATCH /channels/{id}`), unarchive. `create_channel` should also require an existing directory, as `set_channel_cwd` now does. |
| Onboarding starter agents | `GET /templates` returns presets filtered by detected harnesses and tools. `POST /bootstrap {agent_templates, cwd}` creates the agents and #general atomically. |
| "Try asking" prompts | `GET /channels/{id}/suggestions`, generated from the roster's descriptions with the router model and cached per roster. |
| Human profile ("You", "Y") | `GET /me` with a display name, editable. |
| Attachment follow-ups | Remove unsent uploads after a retention window. Add a per-channel quota. Pass PDFs and other files as native inputs where a harness supports them. Serve thumbnails for large images. |
| Proactive agent posts (#infra-alerts "Disk usage on build-02 at 91%") | Agents run today only in response to messages. Scheduled or event-triggered runs need a product decision before a contract. |

Voice input and the theme toggle belong to the frontend and need no backend work.
