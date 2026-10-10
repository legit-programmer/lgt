---
id: 20261008-full-permission-agents
title: "Decision: agents run with full permissions"
tags: [decision, security, harness]
created: 2026-10-08
updated: 2026-10-10
related: [20261008-harness-adapters, 20261008-gateway-http, 20261008-open-gaps, 20261010-desktop-daemon]
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

- The local API is effectively remote code execution for any local process. Manual mode is guarded by loopback binding and the origin policy. Desktop daemon mode additionally requires a per-launch token, protected by an owner-private discovery file. Processes running as the same OS user can read that file; the token is not a sandbox.
- Never bind the backend to a non-loopback address.

## Related

- [Harness adapters](../backend/harness-adapters.md) — where the flags are built.
- [Gateway HTTP](../backend/gateway-http.md) — the origin policy.
- [Open gaps](../status/open-gaps.md) — the launch token.

- [Desktop daemon](../backend/desktop-daemon.md) - discovery, launch tokens, and shutdown.
