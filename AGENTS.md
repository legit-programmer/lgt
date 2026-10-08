# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this project is

Lgt is a local, single-user workspace where one person talks to a team of AI coding agents. Each agent runs a coding CLI already installed on the machine (Codex, Claude Code, Gemini, or a custom stdio command). Agents work in DMs and in channels, where a router picks who handles each unmentioned message.

The repo has two halves:

| Half | Path | Stack |
| --- | --- | --- |
| Backend | `lgt/` | Python 3.13, FastAPI, SQLite. Binds `127.0.0.1`; HTTP + WebSocket; runs agents as subprocesses. |
| Desktop app | `desktop/` | Tauri v2 shell, with a React 19 + TypeScript + Vite UI built from the Ember design in `design/`. |

The backend owns all state, in an append-only event log. The desktop app only displays backend state.

## Start with the knowledge base

**Read `kb/INDEX.md` first.** It is a registry of short, atomic notes on architecture, decisions, operations and status. Each note names the exact files and functions involved. Open the 1–3 notes relevant to your task, then the code they point to.

Good first reads:
- `kb/topics/overview/system-overview.md`: the two halves and the end-to-end message flow.
- `kb/topics/overview/repo-map.md`: which file owns which concern.
- `kb/topics/decisions/_topic.md`: the rules you must not break by accident.

Other references:
- `docs/backend-reference.md`: exact HTTP routes, WebSocket frames and settings. It is authoritative for payloads.
- `docs/custom-harness.md`: the custom harness stdio protocol.
- `design/backend-gaps.md`: open backend contracts (D1–D6) and the implemented checklist.
- `design/README.md` and `design/Lgt Screens.pdf`: the Ember design rules and screens.
- `Multi-Agent Workspace — Backend Spec.md`: the original spec. Decisions in the KB supersede parts of it, such as the mutable channel cwd.

If a KB note disagrees with the code, trust the code and fix the note.

## Rules that matter

- **No frontend workarounds.** The UI never derives, guesses or caches state the server should own. If the design needs data the backend doesn't expose, skip the element in the UI and add the contract to `design/backend-gaps.md`. See `kb/topics/decisions/no-frontend-workarounds.md`.
- **The log is append-only.** Add events; never update or delete them, because SQL triggers enforce it. Edits are `message_edit` events.
- **All channel writes go through the orchestrator's mailbox** (`Orchestrator._call`), which keeps each channel strictly ordered.
- **Desktop actions use HTTP; the WebSocket delivers state.** Don't apply optimistic state; wait for the event.
- **Configuration is explicit.** The original settings have no defaults. Follow `kb/topics/decisions/explicit-configuration.md` when you add one.
- **Agents run with full permissions** on a local, unauthenticated API. Never bind to anything other than loopback.
- **Use the design system.** Use `fv-` classes and Ember tokens (`desktop/src/styles/`), and never hard-code colours. The amber accent is only for "act here", and every status pairs a glyph, a word and a colour.

## Commands

```powershell
# backend
uv sync
uv run pytest -q                                  # ~150 tests, no model calls
uv run python -m lgt --config config.local.json   # copy config.example.json first

# desktop (from desktop/)
pnpm install
pnpm test; pnpm typecheck
pnpm tauri dev                                    # needs the backend and allowed_origins
pnpm tauri build --no-bundle
```

The desktop needs `settings.allowed_origins` to include `http://tauri.localhost`, `tauri://localhost` and `http://localhost:1420`. Sending messages, routing, suggestions and CLI checkpoints call real models, so use a scratch `data_dir` and cwd for experiments.

## When you change something

1. Add or update tests next to the existing suite: `tests/` for the backend, `desktop/src/**/*.test.ts` for the desktop.
2. Update `docs/backend-reference.md` for any API, frame or configuration change, and `design/backend-gaps.md` when a gap opens or closes.
3. Update the affected KB notes (bump `updated`), keep `kb/INDEX.md` and the topic `_topic.md` in sync, and add a line to `kb/topics/status/changelog.md`.
4. Commit at each meaningful checkpoint, with an imperative subject and a body that explains why. Don't add AI co-author or `Co-Authored-By` trailers.
