"""Bounded NDJSON subprocess runners for Claude, Gemini, and custom harnesses."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, AsyncIterator

from .models import NormalizedEvent, Turn
from .processes import ProcessTree, read_lines, spawn_command


def capped_output(value: Any, cap: int) -> dict[str, Any]:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    data = raw.encode("utf-8")
    return {"output": data[:cap].decode("utf-8", "ignore"), "bytes": len(data),
            "lines": len(raw.splitlines()), "truncated": len(data) > cap}


def tool_name(name: str) -> str:
    key = name.lower().replace("_", "")
    if "web" in key or "fetch" in key:
        return "web_fetch"
    if "shell" in key or "bash" in key or "command" in key or "exec" in key:
        return "bash"
    if "grep" in key or "search" in key or "glob" in key:
        return "grep"
    if "edit" in key or "write" in key or "patch" in key or "filechange" in key:
        return "edit"
    if "read" in key:
        return "read"
    return key


def tool_call(call_id: Any, name: str, arguments: Any) -> NormalizedEvent:
    inputs = arguments if isinstance(arguments, dict) else {"value": arguments}
    target = next((str(inputs[k]) for k in ("file_path", "path", "command", "pattern", "query", "url")
                   if k in inputs), "")
    if not target and tool_name(name) == "edit":
        changes = inputs.get("changes")
        if isinstance(changes, list) and changes:
            first = changes[0]
            if isinstance(first, dict):
                target = str(first.get("path") or first.get("file_path") or "")
    if tool_name(name) == "edit" and "old_string" in inputs and "new_string" in inputs:
        target = f"{target} {str(inputs['old_string'])[:60]} → {str(inputs['new_string'])[:60]}"
    normalized = tool_name(name)
    label = {"bash": "Bash", "read": "Read", "edit": "Edit", "grep": "Grep",
             "web_fetch": "Web Fetch"}.get(normalized, name)
    return NormalizedEvent("tool_call", {"tool_call_id": str(call_id), "tool": normalized,
                                         "name": name, "label": label,
                                         "summary": target[:240] or label, "input": inputs})


def tool_result(call_id: Any, value: Any, cap: int, *, is_error: bool = False,
                exit_code: int | None = None, duration_ms: int | None = None) -> NormalizedEvent:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        value = "\n".join(str(item.get("text", item)) for item in value)
    return NormalizedEvent("tool_result", {"tool_call_id": str(call_id), "is_error": is_error,
                                            "exit_code": exit_code, "duration_ms": duration_ms,
                                            **capped_output(value, cap)})


def usage(data: dict[str, Any], *, claude: bool = False, gemini: bool = False) -> NormalizedEvent:
    def number(*keys: str) -> int:
        for key in keys:
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        return 0
    token_in = number("tokens_in", "input_tokens", "inputTokens", "promptTokens")
    token_out = number("tokens_out", "output_tokens", "outputTokens", "candidatesTokens")
    cached = number("tokens_cached_in", "cache_read_input_tokens", "cached_input_tokens", "cachedInputTokens", "cachedContentTokenCount", "cached")
    creation = number("tokens_cache_creation", "cache_creation_input_tokens", "cache_creation_tokens", "cache_write_input_tokens")
    reasoning = number("tokens_reasoning", "reasoning_output_tokens", "thoughtsTokenCount", "reasoningTokens", "thoughts")
    reported_total = number("tokens_total", "total_tokens", "totalTokens", "totalTokenCount")
    total = reported_total or token_in + token_out + (cached + creation if claude else reasoning if gemini else 0)
    return NormalizedEvent("usage", {"tokens_in": token_in, "tokens_out": token_out,
                                      "tokens_cached_in": cached, "tokens_cache_creation": creation,
                                      "tokens_reasoning": reasoning, "tokens_total": total,
                                      "context_tokens": data.get("context_tokens"),
                                      "model_context_window": data.get("model_context_window") or data.get("modelContextWindow")})


def structured_error(message: str, *, exit_code: int | None = None, cancelled: bool = False) -> dict[str, Any]:
    lower = message.lower()
    code = ("cancelled" if cancelled else "auth" if any(x in lower for x in ("auth", "login", "unauthorized"))
            else "oom" if "out of memory" in lower or "oom" in lower
            else "timeout" if "timed out" in lower else "signal" if exit_code is not None and exit_code < 0
            else "harness")
    return {"code": code, "message": message, "exit_code": exit_code,
            "signal": -exit_code if exit_code is not None and exit_code < 0 else None}


class StreamingRunner:
    """One subprocess per turn; subclasses translate their native stream."""

    terminal_is_last = False

    def __init__(self, command: tuple[str, ...], *, tool_output_cap: int, line_limit: int,
                 cancel_grace_seconds: float, log_dir: str | Path) -> None:
        self.command = command
        self.tool_output_cap = tool_output_cap
        self.line_limit = line_limit
        self.cancel_grace_seconds = cancel_grace_seconds
        self.log_dir = Path(log_dir)
        self._tree: ProcessTree | None = None
        self._cancelled = False
        self._finished = asyncio.Event()

    def argv(self, turn: Turn) -> tuple[str, ...]:
        raise NotImplementedError

    def stdin(self, turn: Turn) -> bytes | None:
        return None

    def translate(self, event: dict[str, Any]) -> list[NormalizedEvent]:
        raise NotImplementedError

    async def cancel(self, reason: str) -> None:
        self._cancelled = True
        tree = self._tree
        if tree is None or tree.process.returncode is not None:
            return
        await tree.terminate(self.cancel_grace_seconds)

    async def start(self, turn: Turn) -> AsyncIterator[NormalizedEvent]:
        self._finished.clear()
        self._cancelled = False
        self.log_dir.mkdir(parents=True, exist_ok=True)
        terminal_seen = False
        terminal: dict[str, Any] = {"ok": False, "error": None, "exit_code": None, "cancelled": False}
        proc: asyncio.subprocess.Process | None = None
        argv: tuple[str, ...] = ()
        log_task: asyncio.Task[None] | None = None
        try:
            input_bytes = await asyncio.to_thread(self.stdin, turn)
            argv = self.argv(turn)
            self._tree = await spawn_command(list(argv), turn.channel.cwd,
                                             line_limit=self.line_limit)
            proc = self._tree.process
            yield NormalizedEvent("process_started", {"pgid": proc.pid})
            async def stderr_log() -> None:
                with (self.log_dir / f"{turn.run.run_id}.stderr.log").open("wb") as log:
                    while chunk := await proc.stderr.read(65536):
                        log.write(chunk)
            log_task = asyncio.create_task(stderr_log())
            if input_bytes is not None:
                proc.stdin.write(input_bytes)
                await proc.stdin.drain()
            if proc.stdin:
                proc.stdin.close()
            async for line in read_lines(proc.stdout, self.line_limit):
                if terminal_seen and self.terminal_is_last:
                    raise ValueError("custom harness emitted data after its terminal event")
                try:
                    decoded = json.loads(line)
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError("invalid harness NDJSON") from exc
                if not isinstance(decoded, dict):
                    raise ValueError("harness NDJSON event must be an object")
                for item in self.translate(decoded):
                    if item.kind == "run_finished":
                        terminal_seen = True
                        terminal.update(item.data)
                    else:
                        yield item
            await proc.wait()
            await log_task
            terminal["exit_code"] = proc.returncode
            if proc.returncode:
                terminal["ok"] = False
                terminal["error"] = terminal["error"] or structured_error(
                    f"{argv[0]} exited {proc.returncode}", exit_code=proc.returncode)
            elif not terminal_seen:
                terminal["error"] = structured_error("harness ended without a terminal event")
        except Exception as exc:
            terminal["ok"] = False
            terminal["exit_code"] = proc.returncode if proc else None
            terminal["error"] = structured_error(str(exc), exit_code=terminal["exit_code"])
            if self._tree:
                await self._tree.terminate(0)
                terminal["exit_code"] = self._tree.process.returncode
                if isinstance(terminal["error"], dict):
                    terminal["error"]["exit_code"] = terminal["exit_code"]
        finally:
            if self._tree is not None:
                await self._tree.close()
            if log_task is not None:
                await log_task
            self._tree = None
            self._finished.set()
        terminal["cancelled"] = self._cancelled or terminal["cancelled"]
        if terminal["cancelled"]:
            terminal["ok"] = False
            terminal["error"] = structured_error("run cancelled", cancelled=True)
        yield NormalizedEvent("run_finished", terminal)


class ClaudeRunner(StreamingRunner):
    def argv(self, turn: Turn) -> tuple[str, ...]:
        args = (*self.command, "-p", "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--input-format", "stream-json",
                "--model", turn.agent.model,
                "--append-system-prompt", turn.agent.system_prompt)
        if turn.agent.allowed_tools:
            args += ("--tools", ",".join(turn.agent.allowed_tools),
                     "--disallowedTools", "mcp__*",
                     "--allowedTools", *turn.agent.allowed_tools, "--permission-mode", "dontAsk")
        else:
            args += ("--permission-mode", "bypassPermissions")
        if turn.run.session_mode == "resume" and turn.session and turn.session.harness_session_id:
            args += ("--resume", turn.session.harness_session_id)
        return (*args, *getattr(turn.agent, "extra_args", []))

    def stdin(self, turn: Turn) -> bytes:
        blocks: list[dict[str, Any]] = [{"type": "text", "text": turn.prompt}]
        for attachment in turn.attachments:
            if attachment.media_type not in {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}:
                continue
            blocks.append({"type": "document" if attachment.media_type == "application/pdf" else "image",
                           "source": {"type": "base64", "media_type": attachment.media_type,
                                      "data": base64.b64encode(Path(attachment.path).read_bytes()).decode("ascii")}})
        payload = {"type": "user", "message": {"role": "user", "content": blocks},
                   "parent_tool_use_id": None}
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    def translate(self, event: dict[str, Any]) -> list[NormalizedEvent]:
        kind = event.get("type")
        if kind == "system" and event.get("session_id"):
            return [NormalizedEvent("run_started", {"harness_session_id": event["session_id"]})]
        if kind == "stream_event":
            inner = event.get("event") or {}
            delta = inner.get("delta") or {}
            if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                return [NormalizedEvent("text_delta", {"text": delta.get("text", "")})]
        if kind == "assistant":
            results = []
            for block in (event.get("message") or {}).get("content", []):
                if block.get("type") == "tool_use":
                    results.append(tool_call(block.get("id"), block.get("name", "tool"), block.get("input", {})))
                elif block.get("type") == "text":
                    results.append(NormalizedEvent("message", {"text": block.get("text", "")}))
            return results
        if kind == "user":
            return [tool_result(block.get("tool_use_id"), block.get("content", ""), self.tool_output_cap,
                                is_error=bool(block.get("is_error")))
                    for block in (event.get("message") or {}).get("content", [])
                    if block.get("type") == "tool_result"]
        if kind == "result":
            items = [usage(event.get("usage") or {}, claude=True)] if event.get("usage") else []
            items.append(NormalizedEvent("run_finished", {"ok": not event.get("is_error", False),
                "error": structured_error(str(event.get("result") or event.get("subtype"))) if event.get("is_error") else None,
                "cancelled": False}))
            return items
        return []


class GeminiRunner(StreamingRunner):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._text = ""
        self._has_message = False

    def argv(self, turn: Turn) -> tuple[str, ...]:
        args = (*self.command, "-p", f"{turn.agent.system_prompt}\n\n{turn.prompt}",
                "--output-format", "stream-json", "--model", turn.agent.model,
                "--approval-mode", "yolo")
        if turn.run.session_mode == "resume" and turn.session and turn.session.harness_session_id:
            args += ("--resume", turn.session.harness_session_id)
        return (*args, *getattr(turn.agent, "extra_args", []))

    def translate(self, event: dict[str, Any]) -> list[NormalizedEvent]:
        kind = event.get("type")
        if kind == "init":
            return [NormalizedEvent("run_started", {"harness_session_id": event.get("session_id")})]
        if kind == "message" and event.get("role") == "assistant":
            text = event.get("content", "")
            if event.get("delta"):
                self._text += text
                return [NormalizedEvent("text_delta", {"text": text})]
            self._has_message = True
            return [NormalizedEvent("message", {"text": text})]
        if kind == "tool_use":
            return [tool_call(event.get("tool_id"), event.get("tool_name", "tool"), event.get("parameters", {}))]
        if kind == "tool_result":
            return [tool_result(event.get("tool_id"), event.get("output", ""), self.tool_output_cap,
                                is_error=not event.get("status", "success") == "success")]
        if kind == "result":
            stats = event.get("stats") or {}
            totals = stats.get("model_usage") or stats.get("models") or {}
            if isinstance(totals, dict) and totals and "input_tokens" not in stats:
                tokens = [v.get("tokens") or v for v in totals.values() if isinstance(v, dict)]
                summed = {key: sum(int(t.get(key, 0) or 0) for t in tokens if isinstance(t, dict))
                          for key in ("input", "output", "cached", "thoughts", "total")}
                stats = {**stats, "input_tokens": summed["input"], "output_tokens": summed["output"],
                         "cached_input_tokens": summed["cached"], "reasoningTokens": summed["thoughts"],
                         "total_tokens": summed["total"]}
            items = [usage(stats, gemini=True)]
            if self._text and not self._has_message:
                items.append(NormalizedEvent("message", {"text": self._text}))
            items.append(NormalizedEvent("run_finished", {"ok": event.get("status") == "success",
                "error": structured_error(str(event.get("error", "Gemini run failed"))) if event.get("status") != "success" else None,
                "cancelled": False}))
            return items
        if kind == "error":
            return []
        return []


class CustomRunner(StreamingRunner):
    """Version 1 contract: one request line on stdin; normalized events on stdout."""

    terminal_is_last = True

    def argv(self, turn: Turn) -> tuple[str, ...]:
        return (*turn.agent.command, *getattr(turn.agent, "extra_args", []))

    def stdin(self, turn: Turn) -> bytes:
        payload = {"type": "turn", "version": 1, "run_id": turn.run.run_id,
                   "prompt": turn.prompt, "model": turn.agent.model,
                   "system_prompt": turn.agent.system_prompt,
                   "session_mode": turn.run.session_mode,
                   "session_id": turn.session.harness_session_id if turn.session else None,
                   "allowed_tools": turn.agent.allowed_tools,
                   "attachments": [a.summary() | {"path": a.path} for a in turn.attachments]}
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    def translate(self, event: dict[str, Any]) -> list[NormalizedEvent]:
        kind = event.get("type")
        if kind == "run_started":
            return [NormalizedEvent("run_started", {"harness_session_id": event.get("session_id")})]
        if kind in ("text_delta", "message"):
            return [NormalizedEvent(kind, {"text": str(event.get("text", ""))})]
        if kind == "tool_call":
            call = tool_call(event.get("tool_call_id"), event.get("tool", "tool"), event.get("input", {}))
            if isinstance(event.get("label"), str):
                call.data["label"] = event["label"]
            if isinstance(event.get("summary"), str):
                call.data["summary"] = event["summary"]
            return [call]
        if kind == "tool_result":
            return [tool_result(event.get("tool_call_id"), event.get("output", ""), self.tool_output_cap,
                                is_error=bool(event.get("is_error")), exit_code=event.get("exit_code"),
                                duration_ms=event.get("duration_ms"))]
        if kind == "usage":
            return [usage(event)]
        if kind == "limits":
            return [NormalizedEvent("limits", {"snapshot": event.get("snapshot", {})})]
        if kind == "run_finished":
            error = event.get("error")
            if error is not None and not isinstance(error, dict):
                error = structured_error(str(error), exit_code=event.get("exit_code"))
            return [NormalizedEvent("run_finished", {"ok": event.get("ok") is True,
                "error": error or (structured_error("custom harness failed") if not event.get("ok") else None),
                "exit_code": event.get("exit_code"),
                "cancelled": bool(event.get("cancelled"))})]
        raise ValueError(f"unsupported custom event type: {kind}")
