---
id: 20261008-explicit-configuration
title: "Decision: explicit configuration"
tags: [decision, config]
created: 2026-10-08
updated: 2026-10-18
related: [20261008-runtime-and-config]
summary: Why the original runtime settings have no implicit defaults, why later additions do, and the rule for adding a new setting.
---

# Decision: explicit configuration

> Summary: Why the original runtime settings have no implicit defaults, why later additions do, and the rule for adding a new setting.

## Context

The spec left many numeric values open, such as hop limits, caps and timeouts. Hidden defaults would silently decide them.

## Decision

- Every original `Settings` field must appear in the config file; `load_config` lists any missing or unknown fields. `config.example.json` holds the proposed values.
- `attachment_max_bytes` was added the same way and is required.
- The desktop-era settings have documented defaults, so existing config files keep working: `allowed_origins`, `attachment_channel_quota_bytes`, `attachment_retention_seconds` `thumbnail_max_dimension`, `listen_host`, `listen_port` and `advertised_url`.
- Router settings have been removed. The loader accepts legacy names for checkpoint settings and ignores `route_after_active` and `router_context_events` for existing files.

## Adding a setting

1. Add the field to `Settings` in `lgt/config.py`, with validation in `__post_init__`.
2. Add it to `config.example.json` and to `tests/support.py::settings()`.
3. Decide whether it is required or has a default, and say which in `docs/backend-reference.md` (Configuration).
4. Update [runtime and configuration](../backend/runtime-and-config.md).

## Related

- [Runtime and configuration](../backend/runtime-and-config.md) — the full settings list.
