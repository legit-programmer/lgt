---
id: 20261014-todo
title: TODO
tags: [status]
created: 2026-10-14
updated: 2026-10-14
related: [20261008-routing, 20261008-open-gaps, 20261008-known-issues]
summary: Planned improvements the user has asked for that are not yet designed or scheduled, with the observed problem behind each one.
---

# TODO

> Summary: Planned improvements the user has asked for that are not yet designed or scheduled, with the observed problem behind each one.

Add items at the top. Remove an item in the commit that ships it, and record the change in the [changelog](changelog.md).

## Routing

- **Improve agent-to-agent delegation and handoff.** `parse_transfer` in `lgt/transfers.py` accepts a transfer only when the `lgt-transfer` block is the entire message (`re.fullmatch`). An agent that writes its reply and the transfer block in one message has its transfer silently treated as plain text: nothing is delegated, and nobody is told. Seen on 2026-10-14 in #lgt-workspace, where opus answered the user and appended a delegation to astra in the same message, and the user had to ask for it to be resent alone. Options to weigh: tell the agent when a block is ignored, make the rule more prominent in the routing prompt (`lgt/context.py`), or accept a trailing block after prose without losing the "quoted examples cannot transfer" guarantee. See [routing](../backend/routing.md) for the current handoff and delegation rules.

## Related

- [Routing](../backend/routing.md): the current transfer protocol behind the delegation item.
- [Open gaps](open-gaps.md): backend contracts that block desktop features.
- [Known issues](known-issues.md): behaviors that surprise newcomers but aren't planned work.
