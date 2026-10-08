---
id: 20261008-explicit-configuration
title: "Decision: explicit configuration"
tags: [decision, config]
created: 2026-10-08
updated: 2026-10-08
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
- The desktop-era settings have documented defaults, so existing config files keep working: `allowed_origins`, `attachment_channel_quota_bytes`, `attachment_retention_seconds` and `thumbnail_max_dimension`.
- `route_after_active` is fixed to `false` by the owner's routing override and may not be set.

## Adding a setting

1. Add the field to `Settings` in `lgt/config.py`, with validation in `__post_init__`.
2. Add it to `config.example.json` and to `tests/support.py::settings()`.
3. Decide whether it is required or has a default, and say which in `docs/backend-reference.md` (Configuration).
4. Update [runtime and configuration](../backend/runtime-and-config.md).

## Related

- [Runtime and configuration](../backend/runtime-and-config.md) — the full settings list.
