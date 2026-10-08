# Decisions

Short decision records: context, decision, consequences. Read these before changing the behaviors they cover.

- [No frontend workarounds](no-frontend-workarounds.md) — the UI shows only backend state; gaps go to `design/backend-gaps.md`.
- [HTTP for actions, WebSocket for state](http-actions-ws-state.md) — how the desktop uses the two transports.
- [Channel working directory can change](mutable-channel-cwd.md) — replaces the spec's immutable cwd.
- [Cancelling a queued message can retract it](cancel-retracts-message.md) — `cancel_delivery` semantics.
- [Explicit configuration](explicit-configuration.md) — required settings and how to add one.
- [Agents run with full permissions](full-permission-agents.md) — approval bypass and its security consequences.
