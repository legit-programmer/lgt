---
id: 20261008-origins-and-media
title: Origins, CSP and media loading
tags: [desktop, security, attachments]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-gateway-http, 20261008-attachments, 20261008-running-locally, 20261008-desktop-architecture]
summary: Which origins the backend must allow for each way of running the app, the Tauri CSP, and why attachment thumbnails and downloads are fetched with CORS into blob URLs.
---

# Origins, CSP and media loading

> Summary: Which origins the backend must allow for each way of running the app, the Tauri CSP, and why attachment thumbnails and downloads are fetched with CORS into blob URLs.

## Allowed origins (backend `settings.allowed_origins`)

| Origin | Used by |
| --- | --- |
| `http://tauri.localhost` | The built app on Windows (Tauri v2 default) |
| `tauri://localhost` | The built app on macOS and Linux |
| `http://localhost:1420` | `pnpm tauri dev` and `pnpm dev` (Vite on port 1420) |

Without the matching entry, every request gets `403 local_only` and the app shows its unreachable screen.

## CSP (`desktop/src-tauri/tauri.conf.json`)

| Directive | Allows |
| --- | --- |
| `default-src` | `'self'` |
| `connect-src` | `ipc:`, `http://ipc.localhost`, and loopback HTTP and WS (`127.0.0.1:*`, `localhost:*`) |
| `img-src` | `'self'`, `data:` (DiceBear avatars), `blob:` (attachments), loopback |
| `style-src` | `'self' 'unsafe-inline'` |
| `font-src` | `'self' data:` (bundled fonts) |

## Media loading (`desktop/src/lib/media.ts`)

`<img src>` and download navigations send no `Origin` header. From a different site (`tauri.localhost` or `localhost:1420` versus `127.0.0.1`), `Sec-Fetch-Site: cross-site` then makes the backend reject them.

So `useBlobUrl` and `downloadAttachment` instead fetch with `mode: "cors"`, which sends `Origin`, turn the response into a blob URL, cache it per URL, and render or save from there. This uses the documented endpoints and is not a workaround. Signed URLs are noted as a future option once a launch token exists.

## Related

- [Gateway HTTP](../backend/gateway-http.md) — the server side of the policy.
- [Attachments](../backend/attachments.md) — the routes being fetched.
- [Running locally](../operations/running-locally.md) — a config with these origins.
- [Desktop architecture](desktop-architecture.md) — the shell's capabilities.
