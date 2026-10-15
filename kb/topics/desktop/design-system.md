---
id: 20261008-design-system
title: Ember design system
tags: [desktop, design]
created: 2026-10-08
updated: 2026-10-15
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
  - a three-dot triangle for working, with a static working-coloured label;
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
  - The sidebar and detail panel are solid, unless window glass is on.
  - **Window ground (owner override, 2026-10-09):** pitch black (`--surface-0: #000000` in dark), with no backdrop glows. `fv-backdrop` is a flat `--surface-0`, and the `--backdrop-*` tokens are gone.
  - **Window glass (owner request, 2026-10-15; Windows shell only).** `tauri.windows.conf.json` makes the window transparent with Acrylic, and `lib/windowGlass.ts` applies or clears the effect from the `frosted` preference in `store/ui.ts` (local storage `lgt.surface`, default frosted). With `data-window-glass="on"`, the body clears, `fv-backdrop` takes `--window-glass-ground`, and the sidebar, top bar lead and detail panel take `--window-glass-side` and `--window-glass-detail` tints. Dark keeps the ground transparent. Light uses a heavier Acrylic tint (alpha 200) and a paper ground, because a light sheet over a dark wallpaper otherwise takes the wallpaper's colour and the dark top-bar ink loses contrast. The toggle is **Frosted window** in the channel's top-right menu, under the handoff toggle, and in the command palette. Browsers, mobile, macOS and Linux never show it.
  - **Glass is cheap; repaints are not.** Measured 2026-10-15 with Windows GPU counters while an agent worked: glass at idle cost Lgt about 1% GPU. The animated text shimmer and the smoothly fading working dots repainted every frame, which made Windows recomposite the Acrylic each time (Lgt 21%, and 30% even opaque). The shimmer is now static and the dots step (`steps(2, jump-none)`), bringing glass to about 4%. Keep continuous, per-frame animations off the window. An earlier attempt (`8b592f5`, `b62515b`, reverted 2026-10-09) blamed the blur itself.
- **Top bar:** a 44px row (`--size-topbar`) that is both title bar and app chrome, replacing the grey native frame on Windows and the old in-pane headers. The lead zone continues the sidebar column's `--surface-1`, and the rest sits on the window ground. Caption buttons are 46px wide, as Windows users expect; close hovers to `--failed` with `--on-failed`.
- **Controls:** every control is a pill at `--size-control` (34px) with a gradient, a top sheen and a shadow. Tool rows are compact at `--size-tool-row`.
- **Type:** Figtree for prose and UI, IBM Plex Mono for anything machine-owned (paths, tools, agent names, numbers). Labels are uppercase with 0.9px tracking, and UI copy is sentence case.
- **Motion:** only the stepped working dots and the caret move, and both stop under `prefers-reduced-motion`. Don't add animations that repaint every frame; see the window glass note above.
- **Launch overlay (owner request, 2026-10-10):** `StartupOverlay` covers an abstract workspace silhouette with CSS frost while daemon discovery and workspace loading are pending. A plain centered card holds the Lgt mark on a raised button tile, the title, a caption and a thin indeterminate progress bar (restyled 2026-10-14 to drop the orbiting emblem, overline and pulse dots). The bar uses the working colour, stops motion under `prefers-reduced-motion`, and leaves the top bar available. It does not enable OS window transparency.
- **Agent hover panel:** `components/AgentInference.css` uses `--glass-composer` with `--glass-line`, `--blur-overlay` and `--shadow-overlay` for frosted transparent glass in both themes. Models are selectable cards with a check, and reasoning is a segmented meter whose labels sit under their own segments; amber marks the selection. The panel takes the agent's hue. Provider identity remains fixed, and mode descriptions come from the backend.
- **No emoji anywhere.**

## Related

- [Screens](screens.md) — where each component is used.
- [Desktop architecture](desktop-architecture.md) — styles in the file map.
