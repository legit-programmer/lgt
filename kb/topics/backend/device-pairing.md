---
id: 20261012-device-pairing
title: Device pairing and remote access
tags: [backend, desktop, api, security, config]
created: 2026-10-12
updated: 2026-10-12
related: [20261012-mobile-client, 20261008-gateway-http, 20261008-runtime-and-config, 20261010-desktop-daemon, 20261008-websocket-protocol, 20261008-full-permission-agents, 20261008-system-overview, 20261008-desktop-architecture]
summary: Persistent named device credentials, QR payloads, opt-in remote listening, local administration, and immediate socket revocation.
---

# Device pairing and remote access

Lgt reuses its FastAPI gateway for all clients. One daemon, orchestrator, event log, and human identity serve local desktops and paired devices. There is no outbound tunnel or relay; connectivity is configured separately.

## Listener and authentication

`config.Settings` adds `listen_host` (default `127.0.0.1`, optionally `0.0.0.0`), `listen_port` (default 8000), and `advertised_url` (default null). Wildcard IPv4 listening preserves loopback for administration. Remote startup in `__main__.main` automatically enables daemon authentication; `gateway.create_app` rejects a remote runtime without it. The desktop launcher preserves an ephemeral port for local-only work and uses the configured port for remote listening.

`gateway.authenticate` accepts the per-launch daemon token only from an actual loopback peer. `device_auth.DeviceAuth.authenticate` hashes a paired token, finds a non-revoked device, and updates its last-used time at most once per minute. HTTP sends Bearer credentials; WebSockets authenticate their first cursor frame within five seconds. Origin checks apply to both, independently of authentication. Forwarding headers are not trusted.

## Pairing and administration

All `/devices` routes and `/shutdown` require both loopback and the current local launch token. A paired token has no administration capability even when used locally. `GET /connection` exposes the authenticated device ID and local-admin capability to clients.

`POST /devices` creates a named 256-bit credential and returns the versioned JSON QR payload once with `Cache-Control: no-store`. The `devices` table in `schema.sql` persists only its SHA-256 hash, name, ID, created/last-used/revoked timestamps. `Store` owns persistence. The QR carries the credential directly, remains reusable, and grants access until revoked. Creation requires remote listening and a configured advertised URL.

`GET /devices` lists public metadata, `PATCH /devices/{id}` renames, and `POST /devices/{id}/revoke` idempotently revokes. `DeviceAuth` signals every socket registered to that device through per-connection events. Idle sockets wake and close with 1008; replay and live sends check revocation too. New HTTP requests and socket handshakes fail, while already accepted work continues. Persistent credentials and revocations survive daemon restarts.

## Desktop client

`features/settings/DevicesDialog.tsx` renders local Settings → Devices, QR generation through `qrcode`, and revocation. `ConnectionDialog.tsx` verifies pasted pairing JSON through `/connection` before persisting it under `lgt.pairedConnection`. `api/client.ts` gives stored pairing precedence over local startup and sends credentials only to the selected origin with redirects disabled. Launch tokens stay in memory. `lib/folder.ts` asks for host filesystem paths for remote workspaces. `quit_client` exits a paired desktop without shutting down a previous managed local daemon. The socket client stops retrying after a 1008 close.

The Android and iOS builds of the same app are paired-only clients that scan this QR natively; see [Mobile client](../desktop/mobile-client.md). They use the same versioned QR payload, Bearer requests, and authenticated cursor replay described in [the API reference](../../../docs/backend-reference.md#device-pairing-and-remote-access).

## Validation

`tests/test_devices.py` covers credential hashing, restart persistence, remote origins/authentication, loopback administration, forwarding-header spoofing, all-socket revocation, shared events, and replay. `tests/test_daemon.py` exercises automatic authentication for a real remote listener without `--daemon`. `tests/test_runtime.py` validates network settings. Desktop client and Devices-dialog tests verify persistence, backend validation, and revocation-driven UI updates.

## Related

- [Gateway HTTP](gateway-http.md) — request policy and routes.
- [Runtime configuration](runtime-and-config.md) — listener and advertised origin.
- [Desktop daemon](desktop-daemon.md) — launch token and lifecycle.
- [WebSocket protocol](websocket-protocol.md) — authentication and replay.
- [Full-permission agents](../decisions/full-permission-agents.md) — paired access authorizes agent execution.
- [System overview](../overview/system-overview.md) — shared workspace and message flow.
- [Desktop architecture](../desktop/desktop-architecture.md) — host and paired boot paths.
- [Mobile client](../desktop/mobile-client.md) — native QR scanning on Android and iOS.
