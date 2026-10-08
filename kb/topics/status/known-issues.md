---
id: 20261008-known-issues
title: Known issues and caveats
tags: [status, ops]
created: 2026-10-08
updated: 2026-10-09
related: [20261008-process-hosting, 20261008-testing, 20261008-open-gaps, 20261008-harness-adapters, 20261008-cancel-retracts-message, 20261008-full-permission-agents]
summary: Behaviors and risks that are not bugs in the gap list but will surprise a newcomer — stopped requests staying in context, SDK private access, packaging, bundle size, test and line-ending quirks.
---

# Known issues and caveats

> Summary: Behaviors and risks that are not bugs in the gap list but will surprise a newcomer — stopped requests staying in context, SDK private access, packaging, bundle size, test and line-ending quirks.

## Behavior

- **Stopping a run does not retract the request.** The human message stays in the log, so the agent's next turn sees it and may answer it. Only cancelling a *queued delivery* retracts a message; see [cancel retracts message](../decisions/cancel-retracts-message.md).
- **The default avatar style is DiceBear `bottts`.** The design's blob faces are illustrative; the style is stored per agent (`avatar.style`).
- **Gemini auth is always `unknown`.** There is no read-only check for it.

## Risks

- **Codex SDK private access.** `codex_adapter.py` reads the SDK's private subprocess handle (`_client._client._sync._proc`) and its binary resolver, both pinned to `openai-codex==0.160.1`. Re-test these before upgrading the SDK.
- **Packaging.** `processes.py` and `sdk_host.py` relaunch `sys.executable` with a script, so freezing the backend with PyInstaller or Nuitka breaks child processes. Ship a real interpreter, such as python-build-standalone or PyApp.
- **The local API is unauthenticated.** Any local process can drive full-permission agents until D1 adds a launch token; see [full-permission agents](../decisions/full-permission-agents.md).

- **Window glass is a live blur.** DWM recomposites it every frame, so it runs only while Lgt has focus, and it uses the lighter `blur` effect rather than `acrylic`. Expect a short GPU spike at launch while WebView2 renders the UI.

## Tooling quirks

- **Bundle size.** The Vite build warns about a chunk over 500 kB, because the whole `@dicebear/collection` is bundled so that any stored style renders offline.
- **`tests/test_server.py` boots a real server.** It starts one on a random port, and one environment once hit a local `ConnectTimeout`. Rerun the test before treating that as a regression.
- **Line endings.** Git on Windows warns "LF will be replaced by CRLF". The files are authored with LF.

## Related

- [Process hosting](../backend/process-hosting.md) — the packaging caveat in context.
- [Testing](../operations/testing.md) — how to run suites.
- [Open gaps](open-gaps.md) — tracked contract gaps.
- [Harness adapters](../backend/harness-adapters.md) — SDK usage.
