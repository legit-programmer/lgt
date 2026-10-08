# CLAUDE.md

This file guides Claude Code in this repository. The project guidance shared with every coding agent lives in `AGENTS.md`, imported below.

@AGENTS.md

## Working style for Claude Code

- **Start from the KB.** Open `kb/INDEX.md`, pick notes by their descriptions, and read only those, before searching the code. The notes name the files and functions to open next.
- **Keep the KB current.** When your change alters behavior, update the notes the INDEX points to in the same commit, and add a changelog line. Follow the rules in "How to update this KB" in `kb/INDEX.md`: keep the registry, the topic maps and `related` links in sync.
- **Verify UI changes visually** against a live backend running on a scratch `data_dir`. Headless Edge screenshots with hash routes (`#/c/<channel_id>`, `#/agents/new`, `#/onboarding`) work well; see `kb/topics/operations/testing.md`.
- **Prefer HTTP actions in the desktop code**, and leave `WorkspaceSocket.send` unused; see `kb/topics/decisions/http-actions-ws-state.md`.
- **Model calls cost usage.** Avoid triggering real agent runs, routing or suggestions unless verification needs them. When you do, keep the prompts tiny and use Haiku.
