---
id: 20261008-open-gaps
title: Open gaps
tags: [status, backend, desktop]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-no-frontend-workarounds, 20261008-screens, 20261008-harness-adapters, 20261008-websocket-protocol, 20261008-changelog]
summary: Summary of the open backend contracts (D1–D6) that block desktop features, what the UI shows meanwhile, and where the full contracts live.
---

# Open gaps

> Summary: Summary of the open backend contracts (D1–D6) that block desktop features, what the UI shows meanwhile, and where the full contracts live.

The full contracts are in `design/backend-gaps.md`, under "Open: found while building the desktop app". That file is the source of truth, and this note is a summary. When you close a gap, update both places and the [changelog](changelog.md).

| Id | Gap | Blocks | UI meanwhile |
| --- | --- | --- | --- |
| D1 | Daemon handshake: `daemon.json` port file, launch token, `POST /shutdown`, `api_version`, detached logging | The shell starting and stopping the backend, the tray, notifications, start at login, restart after update | Connects to `LGT_BACKEND_URL`; unreachable screen with Retry |
| D2 | WebSocket head cursor (`GET /events/cursor` or a `cursor` in snapshot frames) | Cheap first connection | Sends `last_id: 0` and ignores replays for closed timelines |
| D3 | Claude `tool_result.duration_ms` is null | Per-tool and group durations | Durations omitted |
| D4 | Tool summaries use absolute paths | Design's relative paths in tool rows and activity lines | Shows the server's summary |
| D5 | `cancelled_by` on cancelled runs | "run cancelled by you" | "run cancelled after Ns" |
| D6 | Cancelling a single tool call | The × on live tool rows | Button omitted |

Still open from the original list is one product decision: proactive scheduled or event-triggered agent posts, such as the #infra-alerts example in the design.

## Related

- [No frontend workarounds](../decisions/no-frontend-workarounds.md) — why these are skipped, not faked.
- [Screens](../desktop/screens.md) — the affected elements.
- [Harness adapters](../backend/harness-adapters.md) — D3 and D4 live here.
- [WebSocket protocol](../backend/websocket-protocol.md) — D2.
