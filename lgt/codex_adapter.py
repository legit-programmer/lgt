"""Codex specialist runs through the official Python app-server SDK."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any, Callable

from openai_codex import (
    ApprovalMode, AsyncCodex, CodexConfig, LocalImageInput, Sandbox, TextInput,
)

from .attachments import VIEWABLE_IMAGE_TYPES
from .models import NormalizedEvent, Session, Turn


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _turn_input(turn: Turn) -> Any:
    """Send attached images as native inputs; the prompt already names every file."""
    images = [a for a in turn.attachments if a.media_type in VIEWABLE_IMAGE_TYPES]
    if not images:
        return turn.prompt
    return [TextInput(turn.prompt), *(LocalImageInput(a.path) for a in images)]


def _item_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(by_alias=True, mode="json")
    if isinstance(item, dict):
        return item
    return vars(item)


def _cap(value: Any, limit: int) -> tuple[str, int]:
    output = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    data = output.encode("utf-8")
    return data[:limit].decode("utf-8", errors="ignore"), len(data)


_TOOL_TYPES = frozenset({
    "commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall",
    "webSearch", "imageGeneration", "collabAgentToolCall",
})
_INPUT_FIELDS = frozenset({
    "id", "type", "command", "cwd", "commandActions", "arguments",
    "server", "tool", "query", "path", "changes", "url",
})


def _tool_input(item: dict[str, Any]) -> dict[str, Any]:
    """Keep only call arguments; completed items also contain uncapped output."""
    return {key: value for key, value in item.items() if key in _INPUT_FIELDS}


def bundled_codex_binary(codex_bin: str | None = None) -> str:
    """Resolve the native CLI installed with the pinned official SDK."""
    if codex_bin is not None:
        return codex_bin
    from openai_codex.client import _resolve_codex_bin

    return str(_resolve_codex_bin(CodexConfig()))


class CodexAppServerRunner:
    """One Codex app-server process and one specialist turn per instance."""

    def __init__(
        self,
        *,
        tool_output_cap: int,
        line_limit: int,
        cancel_grace_seconds: float,
        log_dir: str | Path,
        startup_timeout_seconds: float | None = None,
        client_factory: Callable[[CodexConfig], AsyncCodex] = AsyncCodex,
        launch_args_override: tuple[str, ...] | None = None,
        codex_bin: str | None = None,
    ) -> None:
        if (tool_output_cap <= 0 or line_limit <= 0 or cancel_grace_seconds < 0
                or (startup_timeout_seconds is not None and startup_timeout_seconds <= 0)):
            raise ValueError("caps must be positive and cancellation grace nonnegative")
        self.tool_output_cap = tool_output_cap
        self.line_limit = line_limit
        self.cancel_grace_seconds = cancel_grace_seconds
        self.log_dir = Path(log_dir)
        self.startup_timeout_seconds = startup_timeout_seconds
        self.client_factory = client_factory
        self.launch_args_override = launch_args_override
        self.codex_bin = codex_bin
        self._client: AsyncCodex | None = None
        self._turn_handle: Any = None
        self._cancelled = False
        self._finished = asyncio.Event()

    @staticmethod
    def artifact_exists(session_id: str, cwd: str) -> bool:
        """Check for a persisted rollout artifact without starting Codex."""
        if not session_id or not cwd:
            return False
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        sessions = home / "sessions"
        if not sessions.is_dir():
            return False
        # Rollout filenames end in the thread UUID. The cwd match is separately
        # checked by agent_sessions before this method is called.
        return any(sessions.rglob(f"rollout-*-{session_id}.jsonl"))

    async def probe(self) -> dict[str, Any]:
        """Validate the installed SDK and app-server executable without a model call."""
        from importlib.metadata import version
        binary = bundled_codex_binary(self.codex_bin)
        process = await asyncio.create_subprocess_exec(
            binary, "app-server", "--help",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        help_text = stdout.decode("utf-8", errors="replace")
        if process.returncode or "--listen" not in help_text:
            raise RuntimeError("Codex app-server stdio transport unavailable")
        return {
            "version": version("openai-codex"),
            "capabilities": {
                "app_server": True, "resume": True, "interrupt": True,
                "text_delta": True, "permission_bypass": True,
                "allowed_tools": False,
            },
        }

    def _launch_args(self, run_id: str) -> tuple[str, ...]:
        if self.launch_args_override is not None:
            return self.launch_args_override
        binary = bundled_codex_binary(self.codex_bin)
        log_file = self.log_dir / f"{run_id}.stderr.log"
        return (
            sys.executable, str(Path(__file__).with_name("sdk_host.py")),
            "--log", str(log_file), "--line-limit", str(self.line_limit),
            "--", binary, "app-server", "--listen", "stdio://",
        )

    def _pid(self) -> int | None:
        # The SDK has no public process identifier. This private read is pinned
        # to openai-codex 0.160.1; transport and protocol remain SDK-owned.
        try:
            return self._client._client._sync._proc.pid  # type: ignore[union-attr]
        except AttributeError:
            return None

    def _process(self) -> Any:
        try:
            return self._client._client._sync._proc  # type: ignore[union-attr]
        except AttributeError:
            return None

    def _terminate_host(self) -> None:
        try:
            proc = self._client._client._sync._proc  # type: ignore[union-attr]
            if proc is not None and proc.poll() is None:
                proc.terminate()
        except AttributeError:
            pass

    async def cancel(self, reason: str) -> None:
        self._cancelled = True
        if self._turn_handle is not None:
            try:
                await asyncio.wait_for(self._turn_handle.interrupt(), self.cancel_grace_seconds)
            except (Exception, asyncio.CancelledError):
                self._terminate_host()
        try:
            await asyncio.wait_for(self._finished.wait(), self.cancel_grace_seconds)
        except TimeoutError:
            self._terminate_host()

    async def _startup(self, awaitable):
        try:
            if self.startup_timeout_seconds is None:
                return await awaitable
            return await asyncio.wait_for(awaitable, self.startup_timeout_seconds)
        except TimeoutError:
            self._terminate_host()
            raise TimeoutError("Codex app-server startup request timed out") from None

    async def start(self, turn: Turn):
        """Yield normalized events from a single SDK turn and close its host."""
        self._finished.clear()
        self._cancelled = False
        terminal: dict[str, Any] = {"ok": False, "error": None, "exit_code": None, "cancelled": False}
        started = False
        completed = False
        natural_exit_code: int | None = None
        thread_id: str | None = None
        seen_calls: set[str] = set()
        previous_usage_total: tuple[int, int] | None = None
        process_group: int | None = None
        client_closed = False
        self.log_dir.mkdir(parents=True, exist_ok=True)
        config = CodexConfig(
            cwd=turn.channel.cwd,
            launch_args_override=self._launch_args(turn.run.run_id),
            codex_bin=self.codex_bin,
        )
        client = self.client_factory(config)
        self._client = client
        try:
            await self._startup(client.__aenter__())
            try:
                pid = self._pid()
                if pid is not None:
                    if os.name != "nt" and os.getpgid(pid) == pid:
                        process_group = pid
                    yield NormalizedEvent("process_started", {"pgid": pid})
                instructions = (
                    turn.agent.system_prompt.strip()
                    + "\n\nThe channel working directory is a home base, not a boundary. "
                    "You may read and write elsewhere on this machine as needed."
                )
                common = {
                    "approval_mode": ApprovalMode.deny_all,
                    "sandbox": Sandbox.full_access,
                    "cwd": turn.channel.cwd,
                    "model": turn.agent.model,
                    "developer_instructions": instructions,
                }
                if turn.run.session_mode == "resume":
                    if turn.session is None or not turn.session.harness_session_id:
                        raise ValueError("resume run has no Codex thread ID")
                    thread = await self._startup(client.thread_resume(turn.session.harness_session_id, **common))
                else:
                    thread = await self._startup(client.thread_start(**common))
                thread_id = thread.id
                # The harness has already answered thread setup. Record its
                # identity before awaiting turn/start so cancellation or failure
                # during that request cannot leave a resumed session clean.
                started = True
                yield NormalizedEvent("run_started", {"harness_session_id": thread_id})
                handle = await self._startup(thread.turn(
                    _turn_input(turn),
                    approval_mode=ApprovalMode.deny_all,
                    sandbox=Sandbox.full_access,
                    cwd=turn.channel.cwd,
                    model=turn.agent.model,
                ))
                self._turn_handle = handle
                async for notification in handle.stream():
                    method, payload = notification.method, notification.payload
                    if method == "item/agentMessage/delta":
                        yield NormalizedEvent("text_delta", {"text": _field(payload, "delta", "")})
                    elif method == "item/started":
                        item = _item_dict(_field(payload, "item"))
                        kind = item.get("type")
                        if kind in _TOOL_TYPES:
                            call_id = item.get("id")
                            if call_id:
                                seen_calls.add(call_id)
                            yield NormalizedEvent("tool_call", {
                                "tool_call_id": call_id, "name": kind,
                                "input": _tool_input(item),
                            })
                    elif method == "item/completed":
                        item = _item_dict(_field(payload, "item"))
                        kind = item.get("type")
                        if kind == "agentMessage":
                            yield NormalizedEvent("message", {"text": item.get("text", "")})
                        elif kind in _TOOL_TYPES:
                            call_id = item.get("id")
                            if call_id not in seen_calls:
                                yield NormalizedEvent("tool_call", {
                                    "tool_call_id": call_id, "name": kind,
                                    "input": _tool_input(item),
                                })
                            raw = item.get("aggregatedOutput", item.get("result", item))
                            output, size = _cap(raw, self.tool_output_cap)
                            status = _value(item.get("status", ""))
                            yield NormalizedEvent("tool_result", {
                                "tool_call_id": call_id, "output": output,
                                "bytes": size,
                                "is_error": status in ("failed", "declined", "error"),
                            })
                    elif method == "thread/tokenUsage/updated":
                        token_usage = _field(payload, "token_usage")
                        last = _field(token_usage, "last")
                        total = _field(token_usage, "total")
                        current_total = (
                            int(_field(total, "input_tokens", 0)),
                            int(_field(total, "output_tokens", 0)),
                        ) if total is not None else None
                        if previous_usage_total is None or current_total is None:
                            increment = (
                                int(_field(last, "input_tokens", 0)),
                                int(_field(last, "output_tokens", 0)),
                            )
                        else:
                            increment = (
                                max(0, current_total[0] - previous_usage_total[0]),
                                max(0, current_total[1] - previous_usage_total[1]),
                            )
                        if current_total is not None:
                            previous_usage_total = current_total
                        yield NormalizedEvent("usage", {
                            "tokens_in": increment[0],
                            "tokens_out": increment[1],
                        })
                    elif method == "error":
                        if not _field(payload, "will_retry", False):
                            error = _field(payload, "error")
                            terminal["error"] = str(_field(error, "message", error))
                    elif method == "turn/completed":
                        completed = True
                        status = _value(_field(_field(payload, "turn"), "status"))
                        terminal["ok"] = status == "completed" and not self._cancelled
                        terminal["cancelled"] = status == "interrupted" or self._cancelled
                        if not terminal["ok"] and terminal["error"] is None:
                            terminal["error"] = f"Codex turn {status}"
                if not started:
                    terminal["error"] = "Codex app-server ended before a turn event"
                elif not completed:
                    terminal["error"] = "Codex app-server ended before turn completion"
                proc = self._process()
                if proc is not None:
                    natural_exit_code = proc.poll()
            finally:
                await client.__aexit__(None, None, None)
                client_closed = True
        except Exception as error:
            terminal["ok"] = False
            terminal["error"] = str(error)
        finally:
            if not client_closed:
                self._terminate_host()
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    pass
            if process_group is not None:
                # The SDK reaps its host. Remaining descendants must not
                # survive a host that exited before its own kill watchdog.
                try:
                    os.killpg(process_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc = self._process()
            if proc is not None and natural_exit_code is None:
                # If the process died before SDK close, its status is the real
                # app-server status. A live process is closed after the turn.
                natural_exit_code = proc.poll()
            self._turn_handle = None
            self._finished.set()
            self._client = None
        if natural_exit_code is not None:
            terminal["exit_code"] = natural_exit_code
            if natural_exit_code != 0:
                terminal["ok"] = False
                terminal["error"] = terminal["error"] or f"Codex app-server exited {natural_exit_code}"
        terminal["cancelled"] = terminal["cancelled"] or self._cancelled
        if terminal["cancelled"]:
            terminal["ok"] = False
        yield NormalizedEvent("run_finished", terminal)
