# Lgt

Lgt is a local workspace where one person talks to a team of AI coding agents. Each agent is backed by a coding CLI on your machine. Agents work in direct messages and in channels, where a router hands each message to the right agent. Every channel keeps an append-only event log that survives restarts.

This repository holds the backend: a local FastAPI server with SQLite history, a WebSocket stream, and Codex app-server agents through the official `openai-codex` Python SDK. The desktop UI design is in [`design/`](design/).

## Quick start

```powershell
uv sync
Copy-Item config.example.json config.local.json
uv run python -m lgt --config config.local.json
```

The API documentation is then at <http://127.0.0.1:8000/docs>. Create a Codex agent, then a channel or DM containing its `agent_id`.

The server binds to `127.0.0.1` and accepts only local same-origin requests. It reuses your existing Codex sign-in. The router calls the Claude CLI and falls back to the bundled Codex CLI.

`config.local.json` must set every setting explicitly. Set `checkpoint_mode` to `cli` to enable rolling context summaries, or `deferred` to turn them off.

## Tests

```powershell
uv run pytest -q
```

The suite uses controlled runners and a local app-server fixture. It makes no model calls.

## Documents

- [Backend reference](docs/backend-reference.md): HTTP routes, WebSocket frames, configuration and behavior.
- [Backend gaps](design/backend-gaps.md): what the UI design still needs from the backend.
- [Design system](design/README.md) and [screens](design/Lgt%20Screens.pdf).
- [Original backend spec](Multi-Agent%20Workspace%20%E2%80%94%20Backend%20Spec.md).
