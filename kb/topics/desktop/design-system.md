---
id: 20261008-design-system
title: Ember design system
tags: [desktop, design]
created: 2026-10-08
updated: 2026-10-10
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
- **Your messages (owner override, 2026-10-09):** no `accent-soft` fill, just a quiet hairline (`inset 0 0 0 1px var(--stroke-2)`). Queued messages keep their dashed queued style.
- **Agent avatars:** DiceBear **Critters** (CC0) is the default style, set by the backend (`DEFAULT_AVATAR_STYLE` in `lgt/models.py`). The picker offers Critters variants. Any stored style still renders, because `components/Avatar.tsx` lazy-loads the matching definition.
- **Provider logos:** `components/ProviderLogo.tsx` uses locally bundled Claude, Gemini and Codex artwork in CLI selection, onboarding, previews and conversation metadata. Codex follows the text colour; Claude and Gemini retain their brand colours. Custom or unknown harnesses use the terminal glyph. Asset sources and licensing live in `desktop/src/assets/providers/README.md`. Agent avatars remain independent of provider identity.
- **Agent hue:** the server assigns a `hue` from 0 to 7, mapped to `--agent-violet … --agent-sand` by `lib/agents.ts#hueVar`. Components read it through `--h`.
- **Glass:**
  - The conversation pane (`fv-pane-glass`) is a translucent sheet without its own `backdrop-filter`. A filter there would make the pane a backdrop root and hide the timeline from the composer's blur.
  - **The composer is frosted glass over the timeline (owner request, 2026-10-09).** It floats absolutely at the bottom of the pane with `backdrop-filter: blur(var(--blur-composer))` (12px), so scrolled messages show through it, blurred. The timeline reserves its live height through `--composer-h`.
  - Overlays (`fv-glass`: menus, dialogs, palette, toasts) are glass.
  - The sidebar and detail panel are solid.
  - **Window ground (owner override, 2026-10-09):** pitch black (`--surface-0: #000000` in dark), with no backdrop glows. `fv-backdrop` is a flat `--surface-0`, and the `--backdrop-*` tokens are gone.
  - **OS window glass was tried and dropped (2026-10-09).** A transparent Tauri window with OS acrylic or blur made the side panels frosted over the desktop. DWM recomposites that blur every frame, about 10 points of GPU behind a game with acrylic. A focus-only blur fixed the cost, but the owner chose to keep the window opaque. The commits are `8b592f5` and `b62515b`, both reverted. Don't reintroduce it without the owner asking.
- **Top bar:** a 44px row (`--size-topbar`) that is both title bar and app chrome, replacing the grey native frame on Windows and the old in-pane headers. The lead zone continues the sidebar column's `--surface-1`, and the rest sits on the window ground. Caption buttons are 46px wide, as Windows users expect; close hovers to `--failed` with `--on-failed`.
- **Controls:** every control is a pill at `--size-control` (34px) with a gradient, a top sheen and a shadow. Tool rows are compact at `--size-tool-row`.
- **Type:** Figtree for prose and UI, IBM Plex Mono for anything machine-owned (paths, tools, agent names, numbers). Labels are uppercase with 0.9px tracking, and UI copy is sentence case.
- **Motion:** only the working dots, the shimmer and the caret move, and all three stop under `prefers-reduced-motion`.
- **Launch overlay (owner request, 2026-10-10):** `StartupOverlay` covers an abstract workspace silhouette with CSS frost and an animated Lgt mark while daemon discovery and workspace loading are pending. It uses the working colour, stops motion under `prefers-reduced-motion`, and leaves the top bar available. It does not enable OS window transparency.
- **No emoji anywhere.**

## Related

- [Screens](screens.md) — where each component is used.
- [Desktop architecture](desktop-architecture.md) — styles in the file map.
