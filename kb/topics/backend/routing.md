---
id: 20261008-routing
title: Routing
tags: [backend, routing]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-dispatch-and-queue, 20261008-process-hosting, 20261008-websocket-protocol]
summary: How unmentioned channel messages are routed (Claude, then Codex, then a random member), the routing_decision payload and reason codes, suggested outside agents, and starter-prompt suggestions.
---

# Routing

> Summary: How unmentioned channel messages are routed (Claude, then Codex, then a random member), the routing_decision payload and reason codes, suggested outside agents, and starter-prompt suggestions.

## Files

- `lgt/router.py`: `CLIRouter`, prompt building, and output parsing.
- `lgt/orchestrator.py`: `_route`, `_apply_route`, and `_mention_decision`.
- `lgt/oneshot.py`: `invoke_cli`, which runs the router CLIs without a shell and with bounded output.

## Model routing

1. `_pump` builds a `RoutingRequest`: the channel, a roster (`agent_id`, handle, description, and `busy` for each member, plus outside agents as candidates for suggestions), the last `router_context_events` events as cold-rendered context, and the messages to route.
2. `CLIRouter.route` asks `claude -p` with `router_model` (default `haiku`), with tools disabled and `--dangerously-skip-permissions`. If that fails, it falls back to `codex exec --ephemeral`. There are `router_attempts` tries per provider, each bounded by `router_timeout_seconds`.
3. The model must return strict JSON with `agents`, `reason` and optionally `suggested_agents`. An empty `agents` list is valid.
4. If both providers fail, a random channel member takes the message (`reason_code: "router_failed_random"`, with the error recorded).
5. `_apply_route` appends a `routing_decision` event and enqueues the chosen members. Outside agents are suggestions only and are never dispatched.

## `routing_decision` payload

```json
{"for_seqs": [12], "agents": ["…"], "suggested_agents": ["…"],
 "method": "router" | "mention", "reason_code": "router" | "mention" | "router_failed_random" | "none",
 "reason": "free text", "error": "optional"}
```

Explicit mentions skip the model and write `method: "mention"`, `reason: "explicit mentions"`. The UI renders "routed → none · reason" with **Add &lt;agent&gt;** buttons for the suggestions.

## Suggestions ("Try asking")

`GET /channels/{id}/suggestions` → `Orchestrator.channel_suggestions` asks the router model for three starter prompts based on the roster's descriptions. The result is cached per roster, and concurrent requests share one in-flight task.

## Related

- [Dispatch and queue](dispatch-and-queue.md) — where `awaiting_route` items come from.
- [Process hosting](process-hosting.md) — `invoke_cli` safety limits.
- [WebSocket protocol](websocket-protocol.md) — how decisions reach the UI.
