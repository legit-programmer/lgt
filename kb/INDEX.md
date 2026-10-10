# Lgt knowledge base — index

Architecture, decisions, operations and status for Lgt. Read this file first, then open only the notes you need. Open the code once the notes have told you where to look.

## How to use this KB (for agents)

1. Pick notes from the registry by their descriptions, and prefer opening 1–3 specific notes over scanning everything.
2. New to the repo? Read `20261008-system-overview`, then `20261008-repo-map`, then the topic map (`topics/<topic>/_topic.md`) of the area you'll touch.
3. Notes name the exact files and functions. Treat the code as the final authority. If a note disagrees with the code, trust the code and fix the note.
4. For exact API payloads, use `docs/backend-reference.md`. For open backend contracts, use `design/backend-gaps.md`.
5. Cite the note `id` when you rely on one.

## How to update this KB (for agents)

- **One topic per note.** A changed idea is edited in place, with `updated` bumped. A new idea gets a new note with id `YYYYMMDD-slug`. Ids never change and are never reused.
- **Registry stays in sync.** Every create, rename or delete updates this registry and the topic's `_topic.md` in the same change.
- **Links carry reasons.** Use relative links that say why they connect, and mirror them in the note's `related` frontmatter.
- **Behavior changes touch the KB.** Update the affected notes, and add a line to `20261008-changelog` in the same commit as the code.
- **Tags are controlled.** Use only the tags below; add a new tag here before using it.

## Controlled tags

`overview`, `backend`, `desktop`, `api`, `storage`, `runs`, `routing`, `context`, `harness`, `process`, `attachments`, `ui`, `design`, `config`, `security`, `ops`, `testing`, `decision`, `status`

## Registry

Format: `id` — **Title** — `path` — description.

### overview
- `20261008-glossary` — **Glossary** — `topics/overview/glossary.md` — Definitions of the domain terms (agent, harness, channel, event, seq, chain, hop, run, session, delivery, checkpoint) as the code uses them.
- `20261008-repo-map` — **Repo map** — `topics/overview/repo-map.md` — Every top-level folder and backend module with its responsibility, so you know which file to open for a given concern.
- `20261008-system-overview` — **System overview** — `topics/overview/system-overview.md` — What Lgt is, its two halves (Python backend and Tauri desktop app), and how a message flows from the composer to an agent and back.

### backend
- `20261010-desktop-daemon` - **Desktop daemon lifecycle** - `topics/backend/desktop-daemon.md` - Discovery, detached launch, tokens, shutdown, and the frosted startup screen.
- `20261008-attachments` — **Attachments** — `topics/backend/attachments.md` — Upload storage outside channel directories, size and quota limits, retention of unsent files, binding to exactly one message, thumbnails, and how files reach each harness.
- `20261008-context-and-sessions` — **Context and sessions** — `topics/backend/context-and-sessions.md` — How a turn's prompt is rendered from the log, when a harness session is resumed versus rebuilt cold, how resets and edits invalidate sessions, and how checkpoints summarize old context.
- `20261008-dispatch-and-queue` — **Dispatch and queue** — `topics/backend/dispatch-and-queue.md` — How the orchestrator serializes each channel through a mailbox, moves deliveries through queue states, coalesces messages for busy agents, and starts runs.
- `20261008-event-store` — **Event store** — `topics/backend/event-store.md` — The SQLite schema, the append-only event log and its event kinds, triggers that enforce invariants, migrations, FTS search, and the summary and usage queries.
- `20261008-gateway-http` — **Gateway HTTP API** — `topics/backend/gateway-http.md` — The FastAPI app's local-origin policy, error envelope, request validation style, and a grouped map of HTTP routes with pointers to the authoritative reference.
- `20261008-harness-adapters` — **Harness adapters** — `topics/backend/harness-adapters.md` — The harness registry (discovery, catalogs, capability-based validation, runner factory) and the Codex, Claude, Gemini, and custom adapters that turn CLI output into normalized events.
- `20261008-live-state` — **Live state frames** — `topics/backend/live-state.md` — The server-computed state behind the sidebar, status dots, activity lines, context header and usage — channel summaries, agent statuses, context stats, usage totals, plan limits, profile — and when each is published.
- `20261008-process-hosting` — **Process hosting** — `topics/backend/process-hosting.md` — How CLI child processes are spawned without a shell, grouped so the whole tree can be killed (Windows Job Objects, POSIX process groups), and bounded; plus the Codex SDK byte host and one-shot CLI calls.
- `20261008-routing` — **Routing** — `topics/backend/routing.md` — How unmentioned channel messages are routed (Claude, then Codex, then a random member), the routing_decision payload and reason codes, suggested outside agents, and starter-prompt suggestions.
- `20261008-run-lifecycle` — **Run lifecycle** — `topics/backend/run-lifecycle.md` — Run statuses and the events they emit, how runner output becomes log events, cancellation, failure normalization, and orphan recovery after a crash.
- `20261008-runtime-and-config` — **Runtime and configuration** — `topics/backend/runtime-and-config.md` — How the backend starts (entry point, config loading, lock, harness scan, orchestrator start), every setting, and the data directory layout.
- `20261008-websocket-protocol` — **WebSocket protocol** — `topics/backend/websocket-protocol.md` — The /ws cursor handshake, replay and snapshot order, every server frame type, client commands, and overflow/resync behavior of the event bus.

### desktop
- `20261008-client-state` — **Client state and socket** — `topics/desktop/client-state.md` — The Zustand workspace store (what it holds, how frames are applied, timeline paging), the socket's reconnect and resync logic, and the UI store with hash routing.
- `20261008-design-system` — **Ember design system** — `topics/desktop/design-system.md` — The Ember rules from design/README.md and how they are implemented in tokens.css, components.css and app.css, including agent hues, status glyphs and glass usage.
- `20261008-desktop-architecture` — **Desktop architecture** — `topics/desktop/desktop-architecture.md` — How the shell starts the daemon, shows the launch overlay, and connects the React app, plus a file map of desktop/.
- `20261008-origins-and-media` — **Origins, CSP and media loading** — `topics/desktop/origins-and-media.md` — Which origins the backend must allow for each way of running the app, the Tauri CSP, and why attachment thumbnails and downloads are fetched with CORS into blob URLs.
- `20261008-screens` — **Screens and features** — `topics/desktop/screens.md` — Which desktop/src/features file implements each screen of Lgt Screens.pdf, which backend routes each uses, and which design elements are deliberately omitted.
- `20261008-timeline-model` — **Timeline model** — `topics/desktop/timeline-model.md` — The rules buildTimeline uses to turn a channel's events into blocks — human messages, run segments with tool groups, routing notices, run failures, dividers, notices — and how the Timeline component scrolls and marks read.

### decisions
- `20261008-cancel-retracts-message` — **Decision: cancelling a queued message can retract it** — `topics/decisions/cancel-retracts-message.md` — Semantics of cancel_delivery — which queue items it cancels, when it also deletes the message from every agent's future context, and how it interacts with in-flight routing.
- `20261008-explicit-configuration` — **Decision: explicit configuration** — `topics/decisions/explicit-configuration.md` — Why the original runtime settings have no implicit defaults, why later additions do, and the rule for adding a new setting.
- `20261008-full-permission-agents` — **Decision: agents run with full permissions** — `topics/decisions/full-permission-agents.md` — Why every specialist run bypasses interactive approvals, what each harness is passed, how tool allowlists still restrict Claude, and the security consequences for the local API.
- `20261008-http-actions-ws-state` — **Decision: HTTP for actions, WebSocket for state** — `topics/decisions/http-actions-ws-state.md` — Why the desktop sends every mutation over HTTP and uses the WebSocket only to receive events, deltas and state frames.
- `20261008-mutable-channel-cwd` — **Decision: channel working directory can change** — `topics/decisions/mutable-channel-cwd.md` — Why the original spec's immutable channel cwd was replaced by a guarded change that forces cold rebuilds, and the rules of PUT /channels/{id}/cwd.
- `20261008-no-frontend-workarounds` — **Decision: no frontend workarounds** — `topics/decisions/no-frontend-workarounds.md` — The rule that the UI only displays backend state; when a contract is missing, the feature is skipped and recorded in design/backend-gaps.md instead of being derived or faked on the client.

### operations
- `20261008-conventions` — **Conventions** — `topics/operations/conventions.md` — Coding, documentation and commit conventions for both halves of the repo, and what to update when behavior changes.
- `20261008-running-locally` — **Running locally** — `topics/operations/running-locally.md` — Step-by-step commands to run the backend and the desktop app together for development, including the config the desktop needs and how to point the app at another backend.
- `20261008-testing` — **Testing** — `topics/operations/testing.md` — How to run the backend and desktop test suites, which test file covers which module, the fakes they use, and how UI changes were verified visually.

### status
- `20261008-changelog` — **Changelog** — `topics/status/changelog.md` — Chronological record of what changed in the repo, by commit, so an agent can tell what is new and what superseded the original spec.
- `20261008-known-issues` — **Known issues and caveats** — `topics/status/known-issues.md` — Behaviors and risks that are not bugs in the gap list but will surprise a newcomer — stopped requests staying in context, SDK private access, packaging, bundle size, test and line-ending quirks.
- `20261008-open-gaps` — **Open gaps** — `topics/status/open-gaps.md` — Summary of the open backend contracts (D2–D6) that block desktop features, what the UI shows meanwhile, and where the full contracts live.
