---
id: 20261008-full-permission-agents
title: "Decision: agents run with full permissions"
tags: [decision, security, harness]
created: 2026-10-08
updated: 2026-10-18
related: [20261008-harness-adapters, 20261008-gateway-http, 20261008-open-gaps, 20261010-desktop-daemon, 20261012-device-pairing, 20261013-skill-invocation]
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
| Summarizer | Claude with `--tools ""` and `--dangerously-skip-permissions`; its Codex fallback get `--dangerously-bypass-approvals-and-sandbox` |

`permission_mode` must be `bypass`. Harnesses that can't enforce tool allowlists (Codex, Gemini) reject a nonempty `allowed_tools`, rather than ignoring it silently.

[Skill invocation](../backend/skill-invocation.md) checks explicit `lgt.required_tools` declarations against these allowlists. Claude's native `Skill` tool is selectable in the tool catalog and must be enabled for allowlisted agents to invoke skills. Invocations do not widen the tool policy. Unknown requirements remain unknown; native runtime permission denials produce a failed run and explicit recovery choices.

## Consequences

- The API controls agents with full filesystem permissions. Manual development mode is guarded by loopback binding and the origin policy. Daemon mode requires credentials: an owner-private per-launch token for the local desktop, or a revocable device credential for paired clients. Processes running as the same OS user can read that file; the token is not a sandbox.
- Remote listening is explicitly configurable and always authenticated. Device administration and shutdown require the launch token over actual loopback. Pairing grants full workspace access; clients share the same human identity. See [device pairing](../backend/device-pairing.md).

## Related

- [Harness adapters](../backend/harness-adapters.md) — where the flags are built.
- [Gateway HTTP](../backend/gateway-http.md) — the origin policy.
- [Open gaps](../status/open-gaps.md) — the launch token.

- [Desktop daemon](../backend/desktop-daemon.md) - discovery, launch tokens, and shutdown.

- [Device pairing and remote access](../backend/device-pairing.md) — persistent credentials and local device administration.
