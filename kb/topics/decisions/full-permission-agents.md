---
id: 20261008-full-permission-agents
title: "Decision: agents run with full permissions"
tags: [decision, security, harness]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-harness-adapters, 20261008-gateway-http, 20261008-open-gaps]
summary: Why every specialist run bypasses interactive approvals, what each harness is passed, how tool allowlists still restrict Claude, and the security consequences for the local API.
---

# Decision: agents run with full permissions

> Summary: Why every specialist run bypasses interactive approvals, what each harness is passed, how tool allowlists still restrict Claude, and the security consequences for the local API.

## Context

Runs are headless; no one is there to approve a prompt. The cwd is a home base, not a boundary: agents may read and write anywhere on the machine. The system prompt tells them so (`codex_adapter.py`).

## Decision

| Harness | Flags |
| --- | --- |
| Codex | `ApprovalMode.deny_all` (wire value `approvalPolicy: never`) with `Sandbox.full_access` |
| Claude with an allowlist | `--tools`, `--allowedTools`, `--permission-mode dontAsk`, `--disallowedTools mcp__*` |
| Claude without an allowlist | `--permission-mode bypassPermissions` |
| Gemini | `--approval-mode yolo` |
| Router and summarizer | Claude with `--tools ""` and `--dangerously-skip-permissions`; their Codex fallbacks get `--dangerously-bypass-approvals-and-sandbox` |

`permission_mode` must be `bypass`. Harnesses that can't enforce tool allowlists (Codex, Gemini) reject a nonempty `allowed_tools`, rather than ignoring it silently.

## Consequences

- The local API is effectively remote code execution for any local process. It is guarded only by loopback binding and the origin policy until a launch token exists (D1 in [open gaps](../status/open-gaps.md)).
- Never bind the backend to a non-loopback address.

## Related

- [Harness adapters](../backend/harness-adapters.md) — where the flags are built.
- [Gateway HTTP](../backend/gateway-http.md) — the origin policy.
- [Open gaps](../status/open-gaps.md) — the launch token.
