---
id: 20261008-no-frontend-workarounds
title: "Decision: no frontend workarounds"
tags: [decision, desktop]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-open-gaps, 20261008-client-state, 20261008-live-state]
summary: The rule that the UI only displays backend state; when a contract is missing, the feature is skipped and recorded in design/backend-gaps.md instead of being derived or faked on the client.
---

# Decision: no frontend workarounds

> Summary: The rule that the UI only displays backend state; when a contract is missing, the feature is skipped and recorded in design/backend-gaps.md instead of being derived or faked on the client.

## Context

The owner asked for a solid architecture. Early analysis listed many ways the desktop could compensate for missing endpoints: scanning every channel for status, unread counts in `localStorage`, guessing queue state, computing durations from timestamps. Each of these duplicates server logic and drifts from it.

## Decision

- Every state the UI shows comes from the backend: HTTP for the first load, WebSocket frames for changes.
- When the design needs data the backend doesn't provide, the UI omits that element and the gap is added to `design/backend-gaps.md`, with its contract and what the UI shows meanwhile.
- Pure presentation is fine on the client. Examples are formatting, grouping consecutive tool calls, choosing avatar seeds in the picker, the theme preference, and in-memory drafts.

## Consequences

- Some design elements are missing until the backend adds them: per-tool durations, "cancelled by you", the single-tool ×, and the tray. See [open gaps](../status/open-gaps.md).
- Contributors who add a UI feature must first check that a backend contract exists. If none does, they extend the backend or the gap file; they don't patch around it in the client.

## Related

- [Open gaps](../status/open-gaps.md) — the current list of skipped features.
- [Client state](../desktop/client-state.md) — the store that holds only server state.
- [Live state](../backend/live-state.md) — the server-computed objects that replace client derivations.
