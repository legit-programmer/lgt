---
id: 20261008-conventions
title: Conventions
tags: [ops]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-no-frontend-workarounds, 20261008-testing, 20261008-changelog, 20261008-design-system]
summary: Coding, documentation and commit conventions for both halves of the repo, and what to update when behavior changes.
---

# Conventions

> Summary: Coding, documentation and commit conventions for both halves of the repo, and what to update when behavior changes.

## Code

- **Backend:**
  - Python 3.13, `from __future__ import annotations`, dataclasses in `models.py`.
  - User-safe failures raise `WorkspaceError`, which becomes a 400. Unknown ids raise `KeyError`, which becomes a 404.
  - All channel writes go through `Orchestrator._call`.
  - Events are append-only; add new kinds to `EVENT_KINDS` in `models.py`.
- **Desktop:**
  - TypeScript in strict mode; components are function components.
  - Styling uses `fv-` classes and tokens; no hard-coded colours. See the [design system](../desktop/design-system.md).
  - Server types live in `src/api/types.ts`, and every route goes through `api.*` in `src/api/client.ts`.
- **Comments:** match the surrounding density, and explain *why* rather than *what*.

## When behavior changes

1. Update `docs/backend-reference.md` for any API, frame or configuration change.
2. Update `design/backend-gaps.md` when a gap opens or closes.
3. Update the relevant KB notes, bump their `updated` date, and add a line to the [changelog](../status/changelog.md).
4. Add tests next to the existing suite for that module.

## Commits

- Commit at each meaningful checkpoint.
- The subject is imperative and about 70 characters. The body explains what changed and why, often as bullets.
- Don't add AI co-author or `Co-Authored-By` trailers; this is the repository owner's rule.
- Never commit `config.local.json`, data directories, `desktop/node_modules`, `desktop/dist`, `src-tauri/target` or `*.tsbuildinfo`.

## Related

- [No frontend workarounds](../decisions/no-frontend-workarounds.md) — the main architectural rule.
- [Testing](testing.md) — what to run before committing.
- [Changelog](../status/changelog.md) — where to record changes.
