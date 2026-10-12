---
id: 20261012-mobile-client
title: Mobile client (Android and iOS)
tags: [desktop, ui, security]
created: 2026-10-12
updated: 2026-10-12
related: [20261012-device-pairing, 20261008-desktop-architecture, 20261008-origins-and-media, 20261008-design-system, 20261008-client-state]
summary: How the same Tauri app builds for Android and iOS as a paired-only client - compiled-out daemon, pairing boot, QR scanning, phone layout, back button, and mobile file saving.
---

# Mobile client (Android and iOS)

> Summary: How the same Tauri app builds for Android and iOS as a paired-only client - compiled-out daemon, pairing boot, QR scanning, phone layout, back button, and mobile file saving.

A phone never hosts a workspace. The mobile build is the desktop UI talking to a paired host over the existing [device pairing](../backend/device-pairing.md) contract: Bearer HTTP, the token in the first WebSocket frame, and the versioned QR payload. No backend change is involved.

## Shell (`desktop/src-tauri`)

- `src/lib.rs` compiles `daemon.rs` and its commands (`ensure_backend`, `quit_workspace`, `quit_client`) under `cfg(desktop)` only. Mobile registers the dialog, opener, `barcode-scanner` and `fs` plugins. `Cargo.toml` makes `reqwest`, `url` and `libc` desktop-only and the two mobile plugins mobile-only.
- `capabilities/default.json` is limited to desktop platforms (window controls, folder dialog). `capabilities/mobile.json` grants scanning, `dialog:allow-save`, `fs:allow-write-file` and `fs:allow-exists` scoped to `$DOCUMENT`, URL opening, and `core:app:allow-exit` for the Android back button.
- `gen/android` is the committed output of `pnpm tauri android init`, with launcher icons from `tauri icon`. Debug builds allow cleartext HTTP; release builds do not. `gen/apple` must be generated on macOS with `pnpm tauri ios init`. `Info.ios.plist` is merged into it: the camera usage text, and Files-app visibility for saved attachments. `icons/ios` holds the generated app icons.

## Frontend

- **Platform.** `lib/platform.ts` reads `TAURI_ENV_PLATFORM` (already in Vite's `envPrefix`) at build time: `isMobile`, `isAndroid`, `isIos`. `useCompactLayout()` tracks the 760px phone breakpoint.
- **Boot.** In `api/client.ts`, `resolveBackendUrl()` still prefers a stored pairing. On mobile without one it throws `PairingRequiredError` and never invokes a daemon command. `App.tsx` renders **Pair with your workspace** for that state instead of the unreachable screen.
- **Pairing.** On mobile, `features/settings/ConnectionDialog.tsx` shows **Scan QR code**. `lib/scan.ts` runs the barcode scanner with `windowed: true`: the camera sits behind a transparent webview, `html.is-scanning` hides the page, and `components/ScanOverlay.tsx` draws the frame and Cancel. The scanned text goes through the same `savePairedConnection` verification as a pasted code. **Use local workspace** becomes **Disconnect**.
- **Chrome.** `TopBar.tsx` skips window APIs and drag regions on mobile. At phone width it drops Forward and the "new" menu (the sidebar's section buttons cover it), and drops Back on Android, whose back gesture replaces it. The sidebar's Quit button is hidden: mobile apps don't quit themselves.
- **Panel gestures.** On phone-width touch screens (`useTouchPanels()`, `(max-width: 760px) and (pointer: coarse)`), `lib/gestures.ts` replaces the sidebar and Agents-panel toggles. Swiping right opens the sidebar, or closes the detail panel when it is open. Swiping left opens the detail panel (channels only), or closes the sidebar. A swipe must cover 60px within 600ms and be mostly horizontal. Swipes are ignored in fields, horizontal scrollers, open dialogs, menus, while scanning, and when they selected text. `overscroll-behavior-x: none` keeps browsers from turning them into history navigation. Panels slide in from their side, without motion under reduced-motion settings. Narrow windows with a mouse keep the toggles.
- **Android back.** `useAndroidBackButton` in `App.tsx` closes the innermost layer: an active scan, an open Radix dialog or menu (by dispatching Escape), the phone drawer or panel. Then it walks view history, and exits from the first view.
- **Layout.** At 760px or less (`app.css`, "Phone layout"), the sidebar is a drawer over a scrim, the detail panel is a full-width sheet, and the panes lose their margins. `App.tsx` closes both on every navigation without changing the stored sidebar preference (`ui.setSidebarOpen`). The top bar hides descriptive chips. `.app-shell` uses `100dvh` and safe-area padding (`viewport-fit=cover`). Inputs are 16px to stop iOS focus zoom, and hover-revealed buttons are always visible on touch screens.
- **Paths.** `lib/folder.ts` asks for host paths with `components/PathPrompt.tsx`, an app dialog, instead of `window.prompt`, which mobile webviews don't reliably support. Remote desktops and browsers use it too.
- **Saving attachments.** Mobile webviews ignore `<a download>`. `lib/media.ts` saves through the system picker on Android (`dialog.save` and `fs.writeFile`). On iOS it writes to the app's Documents folder, shown in Files under Lgt, with numbered names for repeats and an info toast. On iOS the plugin's save dialog only exports an empty placeholder.

## Host configuration

- The workspace's `allowed_origins` must include the mobile webview origins: `http://tauri.localhost` on Android, `tauri://localhost` on iOS. See [origins](origins-and-media.md).
- Plain-HTTP advertised URLs work only in Android debug builds. iOS App Transport Security also blocks them, and LAN access triggers the local network prompt. Prefer an HTTPS `advertised_url`, or add the platform exceptions to the generated projects.

## Validation

`App.test.tsx` covers the pairing screen. `gestures.test.ts` covers swipe recognition, the panel each swipe changes, and ignored targets. `client.test.ts` covers mobile boot without daemon discovery. `media.test.ts` covers safe and de-duplicated filenames. `PathPrompt.test.tsx` covers the path dialog. `pnpm tauri android build --debug --apk` builds the Android client. iOS builds need macOS and Xcode.

## Related

- [Device pairing](../backend/device-pairing.md) — the credential and QR contract the phone uses.
- [Desktop architecture](desktop-architecture.md) — the shared shell and boot sequence.
- [Origins and media](origins-and-media.md) — webview origins and blob media.
- [Design system](design-system.md) — tokens used by the phone layout and scanner overlay.
- [Client state](client-state.md) — the UI store's sidebar and panel state.
