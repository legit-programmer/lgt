---
id: 20261008-design-system
title: Ember design system
tags: [desktop, design]
created: 2026-10-08
updated: 2026-10-08
related: [20261008-screens, 20261008-desktop-architecture]
summary: The Ember rules from design/README.md and how they are implemented in tokens.css, components.css and app.css, including agent hues, status glyphs and glass usage.
---

# Ember design system

> Summary: The Ember rules from design/README.md and how they are implemented in tokens.css, components.css and app.css, including agent hues, status glyphs and glass usage.

## Sources

- `design/README.md` is the rulebook, and `design/Lgt Screens.pdf` holds the five reference screens.
- The README refers to `tokens.css` and `components/bundle.css`, but those files were never provided. The desktop versions were derived from the README and the screens:
  - `desktop/src/styles/tokens.css` defines every token for `data-theme="dark"`, the default, and `"light"`.
  - `desktop/src/styles/components.css` implements the `fv-` classes.
  - `desktop/src/styles/app.css` holds the layout and screen-specific styles.

## Rules to keep

- **One accent.** Amber `--accent` means "act here": primary buttons, Send, unread dots, the caret. It never marks status and is never an agent colour.
- **Status is never colour alone.** It always pairs a glyph, a word and a colour:
  - a hollow ring for idle;
  - a three-dot triangle for working, with a shimmering clock;
  - a filled square for failed;
  - a clock for queued;
  - a check for done.
  - These live in `components/Status.tsx`.
- **Agents are rounded squares and people are circles** (`fv-avatar`, `fv-avatar--person`).
- **Agent hue:** the server assigns a `hue` from 0 to 7, mapped to `--agent-violet … --agent-sand` by `lib/agents.ts#hueVar`. Components read it through `--h`.
- **Glass:**
  - Only the conversation pane (`fv-pane-glass`) and overlays (`fv-glass`: menus, dialogs, palette, toasts) are glass.
  - The sidebar and detail panel are solid.
  - The backdrop glows (`fv-backdrop`) show only through glass.
- **Controls:** every control is a pill at `--size-control` (34px) with a gradient, a top sheen and a shadow. Tool rows are compact at `--size-tool-row`.
- **Type:** Figtree for prose and UI, IBM Plex Mono for anything machine-owned (paths, tools, agent names, numbers). Labels are uppercase with 0.9px tracking, and UI copy is sentence case.
- **Motion:** only the working dots, the shimmer and the caret move, and all three stop under `prefers-reduced-motion`.
- **No emoji anywhere.**

## Related

- [Screens](screens.md) — where each component is used.
- [Desktop architecture](desktop-architecture.md) — styles in the file map.
