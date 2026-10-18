---
id: 20261013-skill-invocation
title: Skill discovery and invocation
tags: [backend, harness, routing, desktop, security]
created: 2026-10-13
updated: 2026-10-18
related: [20261008-harness-adapters, 20261008-routing, 20261008-full-permission-agents, 20261008-screens]
summary: Harness-owned installations, server-computed executors, explicit channel and DM selection, native invocation, and declared/runtime permission checks.
---

# Skill discovery and invocation

`lgt/skills.py` owns `Skill`, `ClaudeSkillDiscovery`, `CodexSkillDiscovery`, requirement parsing, and eligibility. `HarnessRegistry.skill_adapters` is the discovery extension point; `discover_skills` isolates errors per harness. Codex calls typed native `skills/list` through the pinned SDK; Claude reads effective user/project/local skills, legacy commands, plugin installations and enabled settings. Identical names across harnesses keep separate installation IDs. Gemini/custom discovery is not yet implemented.

`Orchestrator.channel_skills` and `_skill_catalog` compute candidate reasons, eligible members, primary defaults and recommendations. `invoke_skill` and `send_message` validate and append through the channel mailbox. Skills preserve the primary and run in separate queue batches. A non-primary executor requires explicit selection. DMs never execute through a different agent. `_execute` rechecks queued installations and configurations before starting. Backend changes wait for active runs to finish and then cold-render the stored transcript.

Requirements are explicit `lgt.required_tools` frontmatter; absent declarations are unknown. Claude `allowed-tools` is not a required-tool declaration. Allowlisted Claude agents need the native `Skill` tool enabled. No invocation changes the agent's tool policy. Native `Skill` invocation and Codex `SkillInput` preserve harness loading and arguments. Claude runtime `permission_denials` become `permission` failures; incompatible queued invocations fail with `skill_unavailable`. Terminal events carry the skill snapshot for recovery.

`Composer.tsx` displays `/` and `/list` results from `GET /channels/{id}/skills`, uses `POST …/skills/invoke`, and keeps agent selection in its draft. `SkillDialog.tsx` offers eligible members, adding a compatible existing agent, explicitly changing a backend/tools, or creating an agent for the channel. `SkillRecovery.tsx` exposes settings and explicit retries after permission/availability failures. The UI consumes server eligibility and never infers write requirements from prose.

Tests: `tests/test_skills.py`, `desktop/src/features/channel/Skills.test.tsx`; recorded/fake runners do not call models. Exact payloads live in [the backend reference](../../../docs/backend-reference.md#skill-discovery-and-invocation).

## Related

- [Harness adapters](harness-adapters.md) — discovery and native runner selection.
- [Routing](routing.md) — channel ownership remains stable through skill dispatch.
- [Full-permission agents](../decisions/full-permission-agents.md) — actual harness tool enforcement.
- [Screens](../desktop/screens.md) — composer and agent settings.
