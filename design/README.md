Lgt is a desktop workspace where a person talks to a team of AI agents, each backed by a local CLI. Ember is its visual language: dark-first, warm charcoal with one amber accent, soft tactile controls (pill buttons with a gentle gradient, top sheen and drop shadow), roomy rounded overlays, and a mono edge wherever the machine is talking. Build every Lgt screen from these tokens and the `fv-` component classes: load `tokens.css`, then `components/bundle.css`, then Figtree and IBM Plex Mono from Google Fonts, and set `data-theme="dark"` or `"light"` on the root.

## Principles

- **Messages first, machinery second.** Human and agent prose sits on `surface-2` in `body`. Tool calls, results and notices sit in `well` in `mono`/`meta` and `text-3`. Never make a tool row louder than the message it belongs to.
- **Status is never colour alone.** Every status pairs a glyph, a word and a colour: hollow ring + "idle" (`idle`), three-dot triangle + "working 0:42" with a skeleton shimmer (`working`, plain white / ink), filled square + "failed" (`failed`), clock + "queued → reviewer" (`queued`), check + "done" (`success`).
- **One accent.** `accent` amber means "act here": primary buttons, send, toggles that are on, unread markers, the streaming caret. It never marks status and never becomes an agent colour.
- **Soft to touch, calm to read.** Every control is a pill (`radius-full`) at `size-control` (34px) with a two-stop gradient (`button-hi` → `button-lo`, or `accent-hi` → `accent-lo` for primary), a 1px `button-sheen` top highlight and `shadow-button` / `shadow-primary` beneath. Containers round up as they grow: `radius-md` rows and inputs, `radius-lg` menus and wells, `radius-xl` the composer and dialogs. Tool rows stay compact at `size-tool-row` (26px). No motion except the working dots, the working text shimmer and the streaming caret; all stop under `prefers-reduced-motion` (the three dots stay as a still triangle and the text sits at full `working`).

## Glass: where it goes and where it does not

The **chat column is glass**; the side panels are not.

- Put `fv-backdrop` on the window root: `surface-0` with three soft glows (`backdrop-ember`, `backdrop-rust`, `backdrop-dusk`). The glows are only ever seen through glass.
- Wrap the conversation pane — header, timeline and composer — in `fv-pane-glass`: `glass-pane` fill, `glass-pane-line` edge, `radius-xl` corners, `blur(var(--blur-pane)) saturate(140%)`. Inset it 8px from the window edge so it reads as a sheet floating between the side panels. Inside it, `well`, `surface-3` and the strokes switch to their glass versions automatically (`glass-pane-well`, `glass-pane-raised`, `glass-pane-line`), so tool rows, notices and chips turn translucent too.
- The composer sits on the pane in `glass-composer`, lighter than the pane so it floats.
- Menus, popovers, the command palette, tooltips, toasts and dialogs are glass too: `fv-glass` (`glass-overlay`, `glass-line`, `shadow-overlay`) with a heavier `blur-overlay` (36px) and a slight darken, so messages behind a menu melt into soft colour and the menu text stays crisp.

Stay **solid**: the left sidebar (`surface-1`), the right detail panel (`surface-2`, raised parts on `surface-3`), forms and settings screens. Message blocks themselves get no extra glass — they sit flat on the pane so scrollback stays crisp at thousands of messages.

## Colour

- Grounds step up in order: `surface-0` window → `surface-1` sidebar → `surface-2` pane → `surface-3` raised → `surface-4` hover. `well` is recessed: tool rows, code, paths, inputs.
- Text: `text-1` for prose and names, `text-2` for secondary copy and labels, `text-3` for meta. All three hold 4.5:1 on every surface and on `well` in both themes.
- Lines: `stroke-1` hairlines between messages, `stroke-2` for headers and divider rules, `stroke-control` (3:1+) for input, toggle and secondary-button borders.
- The person's own messages tint with `accent-soft`; mentions and links use `accent-text`. Put `on-accent` on every `accent` fill — never white.
- Focus: a solid 2px `focus` ring with 2px offset on every interactive element.

## Agent identity

Each agent is assigned one hue from `agent-violet`, `agent-sky`, `agent-pink`, `agent-green`, `agent-lime`, `agent-plum`, `agent-indigo`, `agent-sand`, in creation order, and keeps it for life. Set it once with `style="--h: var(--agent-sky)"`; `fv-avatar`, `fv-name` and `fv-chip` derive their tints from `--h`. The first letter of the agent name, in `mono`, is the avatar glyph.

- **Agents are rounded squares** (`radius-sm`); **people are circles** (`radius-full`). This is the fastest way to tell who is speaking.
- Status rides the avatar's bottom-right corner as an `fv-dot`.
- Never assign `accent`, `working`, `failed` or `queued` as an agent hue.

## Type

Figtree for prose and UI, IBM Plex Mono for anything the machine owns (load Figtree 400–700 and Plex Mono 400–600 from Google Fonts).

- `body` for all message prose. `title` for the channel name and panel titles. `display` only on empty states.
- `agent-name` for agent names everywhere. `mono` for paths, tool names, tool inputs, inline code and slash commands. `meta` for times, sizes, durations and CLI labels.
- `label` for section labels: UPPERCASE Figtree 600 with 0.9px tracking, e.g. DIRECT MESSAGES, CHANNELS, CONVERSATION. Menus group items under these labels with a `fv-menu-sep` rule between groups. UI copy is sentence case; never Title Case buttons.

## Message blocks

The timeline is built from these blocks only (see each component):

| Block | Component | Ground |
| --- | --- | --- |
| Human message | `fv-msg fv-msg--human` | `accent-soft`, circle avatar |
| Agent message | `fv-msg` with `fv-name` + `fv-cli` | none (flat on `surface-2`), square avatar |
| Tool call / result / error / group | `fv-tools` → `fv-tool` | `well`; error rows `failed-soft` |
| Routing notice | `fv-notice` | none; `meta` in `text-3` |
| Failed / cancelled run | `fv-run` | `failed-soft` / `surface-3` |
| Streaming | `fv-msg fv-msg--live` + `fv-caret` | left-fading `working-soft` |
| Queued | `fv-msg fv-msg--queued` | `queued-soft`, dashed edge |
| Context reset / checkpoint | `fv-divider--reset` / `fv-divider--checkpoint` | rule only |

Consecutive messages from the same speaker drop the header (`fv-msg--cont`). Tool groups of two or more consecutive calls collapse to one `fv-tool--group` row: "ran 4 tools · read · grep · edit · bash · 1 err · 6.2s".

## Layout

Three regions: sidebar `size-sidebar` (260px) on `surface-1`, the conversation pane (fluid) on `surface-2`, and a collapsible detail panel `size-detail` (360px) on `surface-2` separated by `stroke-1`. Pane padding is `space-400`; gap between timeline blocks is `space-300`; message content aligns to a 44px text column (avatar 26px + `space-200` + padding).

## Content

- Short, literal meta: "routed → coder · explicit mention", "queued → reviewer", "ran 3 tools · pass · 9.4s".
- Name the agent and the cause in every failure: "shell-ops run failed · codex exited 137 (out of memory) after 2m 31s".
- Numbers and units in `mono`: "48.2k / 3.1k", "$0.41", "2m 31s".
- No emoji anywhere.

## Iconography

Stroke icons on a 24px grid, 2px stroke, round caps and joins, drawn at 12–16px in `currentColor`. Lucide is the recommended set (the shapes used in the previews follow it): file, search, terminal, pencil, layers, chevron, alert-triangle, clock, rotate-ccw, bookmark, arrow-right, ban, square (stop), x, plus, settings, hash, folder, at-sign, slash, paperclip, mic, arrow-up. No icon set has been bundled yet — pick Lucide or swap these names for your own.
