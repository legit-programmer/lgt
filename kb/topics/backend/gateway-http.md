---
id: 20261008-gateway-http
title: Gateway HTTP API
tags: [backend, api, security]
created: 2026-10-08
updated: 2026-10-10
related: [20261008-websocket-protocol, 20261008-origins-and-media, 20261008-http-actions-ws-state, 20261008-attachments, 20261010-desktop-daemon]
summary: The FastAPI app's local-origin policy, error envelope, request validation style, and a grouped map of HTTP routes with pointers to the authoritative reference.
---

# Gateway HTTP API

> Summary: The FastAPI app's local-origin policy, error envelope, request validation style, and a grouped map of HTTP routes with pointers to the authoritative reference.

The authoritative route table and payload details are in [docs/backend-reference.md](../../../docs/backend-reference.md). This note explains the design and where to look in `lgt/gateway.py`.

## Local-origin policy (`_scope_is_local_and_same_origin`)

A request must pass all of these checks:
- the TCP peer is loopback;
- the `Host` header is a loopback authority;
- the `Origin` header is either the same origin, or an exact entry in `settings.allowed_origins`, such as `http://tauri.localhost`, `tauri://localhost` or `http://localhost:1420`.

Requests without `Origin` are allowed unless `Sec-Fetch-Site` says `cross-site` or `same-site`. Allowed origins receive CORS headers, and preflight permits `GET, POST, PUT, PATCH, DELETE` with `Content-Type` and `Authorization`. The WebSocket endpoint applies the same check. Failures return `403 local_only`.

## Daemon authentication

In daemon mode, `create_app(..., daemon=...)` requires a Bearer token on every HTTP request except allowed preflights. `/health` returns `{status, application, api_version, pid}`. `/shutdown` requests graceful termination and is unavailable in manual mode.

## Errors

Every error uses the envelope `{"error": {"code", "message"}}`:

| Status | Codes |
| --- | --- |
| 401 | `unauthorized` (daemon token missing or invalid) |
| 400 | `invalid_request` (from `WorkspaceError` / `ValueError`) |
| 404 | `not_found` (from `KeyError`) |
| 409 | `conflict` (SQLite integrity) |
| 413 | `too_large` |
| 415 | `unsupported_media_type` / `invalid_image` |

Request validation errors stay FastAPI's 422 `detail` list. Request bodies are strict Pydantic models (`_StrictModel`: `extra="forbid", strict=True`).

## Route groups

| Group | Routes |
| --- | --- |
| Health and catalog | `/health`, `/shutdown`, `/harnesses`, `/harnesses/scan`, `/harnesses/custom/probe`, `/harnesses/{h}/limits`, `/templates`, `/bootstrap`, `/commands`, `/me` |
| Agents | `/agents`, `/agents/status`, `/agents/{id}` (GET, PUT), `/agents/{id}/retire` and `DELETE /agents/{id}` (soft retirement) |
| Channels | `/channels` (summaries), `PATCH /channels/{id}` (rename), `/archive`, `/unarchive`, `/read`, `/context`, `/suggestions`, `/members` (GET, POST, DELETE), `/cwd`, `/queue`, `/new` |
| Messages | `POST /channels/{id}/messages`, `PATCH …/messages/{seq}` (edit or delete), `POST …/messages/{seq}/cancel` |
| Events and runs | `/channels/{id}/events` (scrollback), `/channels/{id}/runs`, `/runs`, `/runs/{id}`, `/runs/{id}/log`, `/runs/{id}/cancel` |
| Attachments | `POST /channels/{id}/attachments`, `/attachments/{id}`, `/meta`, `/thumbnail`, `DELETE` |
| Insight | `/usage?group_by=agent|channel|day`, `/search?q=` |

Every channel-scoped route calls `_require_channel`, which returns 404 unless the local human is a member.

## Related

- [WebSocket protocol](websocket-protocol.md) — the live half of the API.
- [Origins and media](../desktop/origins-and-media.md) — the client side of the origin policy.
- [HTTP for actions, WebSocket for state](../decisions/http-actions-ws-state.md) — how the desktop uses the API.
- [Attachments](attachments.md) — upload and serving rules.

- [Desktop daemon](desktop-daemon.md) - discovery, launch tokens, and shutdown.
