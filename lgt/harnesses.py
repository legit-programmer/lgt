"""Discovery, capabilities, validation, and runner selection for local CLIs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import math
from pathlib import Path
from typing import Any

from openai_codex import AsyncCodex, CodexConfig

from .codex_adapter import CodexAppServerRunner, bundled_codex_binary
from .models import Agent, WorkspaceError
from .oneshot import CLIOutputLimitError, CLIProcessError, invoke_cli
from .processes import read_lines, spawn_command
from .streaming_adapter import ClaudeRunner, CustomRunner, GeminiRunner


CAPABILITIES = ("resume", "interrupt", "text_delta", "allowed_tools", "image_input", "usage", "rate_limits")
CLAUDE_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebFetch", "WebSearch")
CODEX_TOOLS = ("Bash", "Read", "Edit", "Grep", "WebSearch")
GEMINI_TOOLS = ("run_shell_command", "read_file", "write_file", "replace", "glob",
                "grep_search", "web_fetch", "google_web_search")


def canonical_harness(value: str) -> str:
    return "claude" if value == "claude_code" else value


def _model(model_id: str, description: str, default: bool = False) -> dict[str, Any]:
    return {"id": model_id, "label": model_id.title(), "description": description, "default": default}


def _tools(names: tuple[str, ...]) -> list[dict[str, str]]:
    return [{"id": name, "label": name, "description": f"Use the {name} tool"} for name in names]


class HarnessRegistry:
    def __init__(self, settings: Any, codex_bin: str | None = None,
                 claude_command: tuple[str, ...] = ("claude",),
                 gemini_command: tuple[str, ...] = ("gemini",)) -> None:
        self.settings = settings
        self.codex_bin = codex_bin
        self.claude_command = claude_command
        self.gemini_command = gemini_command
        self._catalog: list[dict[str, Any]] = []
        self._custom_cache: dict[tuple[str, ...], dict[str, Any]] = {}
        self._refresh_static()

    def _refresh_static(self) -> None:
        definitions = (
            ("codex", (self.codex_bin or bundled_codex_binary(),),
             {"resume": True, "interrupt": True, "text_delta": True, "allowed_tools": False,
              "image_input": True, "usage": True, "rate_limits": True},
             [], CODEX_TOOLS),
            ("claude", self.claude_command,
             {"resume": True, "interrupt": True, "text_delta": True, "allowed_tools": True,
              "image_input": True, "usage": True, "rate_limits": False},
             [_model("sonnet", "Balance of speed and depth", True),
              _model("opus", "Deep reasoning"), _model("haiku", "Fast responses")], CLAUDE_TOOLS),
            ("gemini", self.gemini_command,
             {"resume": True, "interrupt": True, "text_delta": True, "allowed_tools": False,
              "image_input": False, "usage": True, "rate_limits": False},
             [_model("auto", "CLI selects a suitable model", True),
              _model("pro", "Complex reasoning"), _model("flash", "Fast balanced responses"),
              _model("flash-lite", "Fast simple responses")], GEMINI_TOOLS),
            ("custom", (), {name: False for name in CAPABILITIES}, [], ()),
        )
        self._catalog = []
        for name, command, capabilities, models, tools in definitions:
            binary = command[0] if command else None
            path = (shutil.which(binary) or (str(Path(binary).resolve()) if binary and Path(binary).is_file() else None)) if binary else None
            self._catalog.append({"harness": name, "found": bool(path) if binary else True,
                "path": path, "version": None, "auth": "unknown", "capabilities": capabilities,
                "models": models, "tools": _tools(tools)})

    async def scan(self) -> list[dict[str, Any]]:
        self._refresh_static()
        for item in self._catalog:
            if not item["found"] or item["harness"] == "custom":
                continue
            cmd = (self.claude_command if item["harness"] == "claude" else
                   self.gemini_command if item["harness"] == "gemini" else (item["path"],))
            try:
                code, stdout, stderr = await self._command((*cmd, "--version"))
                if code == 0:
                    item["version"] = (stdout or stderr).strip()[:160]
            except (OSError, TimeoutError):
                pass
            if item["harness"] == "claude":
                try:
                    code, _, _ = await self._command((*self.claude_command, "auth", "status"))
                    item["auth"] = "signed_in" if code == 0 else "signed_out"
                except (OSError, TimeoutError):
                    pass
            if item["harness"] == "codex":
                try:
                    async def codex_catalog() -> tuple[list[dict[str, Any]], str]:
                        async with AsyncCodex(CodexConfig(codex_bin=self.codex_bin,
                                                         cwd=str(self.settings.data_dir))) as client:
                            response = await client.models()
                            models = [{"id": model.model, "label": model.display_name,
                                       "description": model.description, "default": model.is_default}
                                      for model in response.data]
                            try:
                                account = await asyncio.wait_for(client.account(), 2)
                                auth = "signed_in" if getattr(account, "account", None) else "signed_out"
                            except Exception:
                                auth = "unknown"
                            return models, auth
                    item["models"], item["auth"] = await asyncio.wait_for(codex_catalog(), 8)
                except Exception:
                    pass
            elif item["harness"] in ("claude", "gemini"):
                try:
                    _, help_text, _ = await self._command((*cmd, "--help"))
                    if help_text:
                        required = ("--output-format", "--resume")
                        for flag, marker in (("text_delta", "stream-json"), ("resume", "--resume")):
                            item["capabilities"][flag] = marker in help_text
                        if not all(marker in help_text for marker in required):
                            item["capabilities"]["usage"] = False
                        if item["harness"] == "claude":
                            item["capabilities"]["allowed_tools"] = "--tools" in help_text
                            item["capabilities"]["image_input"] = "--input-format" in help_text
                except (OSError, TimeoutError):
                    pass
        return self.list()

    @staticmethod
    async def _command(argv: tuple[str, ...], timeout: float = 5) -> tuple[int, str, str]:
        try:
            stdout = await invoke_cli(list(argv), os.getcwd(), "", timeout, output_limit_bytes=65536)
            return 0, stdout, ""
        except CLIProcessError as exc:
            return exc.returncode, "", exc.stderr
        except CLIOutputLimitError:
            return 1, "", "CLI probe output exceeded 65536 bytes"

    def list(self) -> list[dict[str, Any]]:
        return [dict(item, capabilities=dict(item["capabilities"]),
                     models=list(item["models"]), tools=list(item["tools"])) for item in self._catalog]

    async def probe_custom(self, command: list[str], extra_args: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            raise WorkspaceError("custom harness requires a nonempty command argv")
        extra_args = extra_args or []
        if not isinstance(extra_args, list) or any(not isinstance(x, str) or not x or "\x00" in x
                                                   or x.startswith("--lgt-") for x in extra_args):
            raise WorkspaceError("invalid custom extra_args")
        if any("\x00" in x for x in command):
            raise WorkspaceError("invalid custom command argv")
        argv = (*command, *extra_args)
        if argv in self._custom_cache:
            return dict(self._custom_cache[argv])
        binary = shutil.which(command[0]) or (str(Path(command[0]).resolve()) if Path(command[0]).is_file() else None)
        if not binary:
            raise WorkspaceError("custom harness command was not found")
        tree = None
        stderr_task: asyncio.Task[None] | None = None
        try:
            tree = await spawn_command([*argv, "--lgt-probe"], os.getcwd(), line_limit=65536)
            tree.process.stdin.close()
            async def discard_stderr() -> None:
                while await tree.process.stderr.read(65536):
                    pass
            stderr_task = asyncio.create_task(discard_stderr())
            async with asyncio.timeout(3):
                lines = []
                async for line in read_lines(tree.process.stdout, 65536):
                    lines.append(line)
                    if len(lines) > 1:
                        raise WorkspaceError("custom harness probe emitted multiple events")
                await tree.process.wait()
                await stderr_task
            if tree.process.returncode != 0 or not lines:
                raise WorkspaceError("custom harness probe failed")
            contract = json.loads(lines[0])
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            raise WorkspaceError("custom harness probe failed") from exc
        finally:
            if tree is not None:
                await tree.close()
            if stderr_task is not None:
                await stderr_task
        if not isinstance(contract, dict) or contract.get("contract_version") != 1 or contract.get("type") != "probe":
            raise WorkspaceError("custom harness requires LGT NDJSON contract version 1")
        caps = contract.get("capabilities")
        models = contract.get("models")
        tools = contract.get("tools")
        if not isinstance(caps, dict) or any(type(caps.get(key)) is not bool for key in CAPABILITIES):
            raise WorkspaceError("custom harness supplied invalid capabilities")
        if caps["resume"]:
            raise WorkspaceError("custom harness resume is not supported by the artifact contract")
        if not isinstance(models, list) or not models or not all(
            isinstance(model, dict) and isinstance(model.get("id"), str) and model["id"]
            and isinstance(model.get("label"), str) and isinstance(model.get("description"), str)
            and type(model.get("default")) is bool for model in models
        ):
            raise WorkspaceError("custom harness supplied invalid model catalog")
        if not isinstance(tools, list) or not all(
            isinstance(tool, dict) and isinstance(tool.get("id"), str) and tool["id"]
            and isinstance(tool.get("label"), str) and isinstance(tool.get("description"), str)
            for tool in tools
        ):
            raise WorkspaceError("custom harness supplied invalid tool catalog")
        descriptor = {"harness": "custom", "found": True, "path": binary,
                      "version": str(contract.get("version", "1")), "auth": "unknown",
                      "capabilities": {key: caps[key] for key in CAPABILITIES},
                      "models": models, "tools": tools}
        self._custom_cache[argv] = descriptor
        return dict(descriptor)

    async def prepare_agent(self, agent: Agent) -> None:
        if canonical_harness(agent.harness) == "custom":
            await self.probe_custom(getattr(agent, "command", []), getattr(agent, "extra_args", []))

    def capabilities_for(self, agent: Agent) -> dict[str, bool]:
        harness = canonical_harness(agent.harness)
        if harness == "custom":
            command = getattr(agent, "command", [])
            extra = getattr(agent, "extra_args", [])
            if not isinstance(command, list) or not isinstance(extra, list):
                raise WorkspaceError("custom harness command must be probed")
            entry = self._custom_cache.get((*command, *extra))
        else:
            entry = next((item for item in self._catalog if item["harness"] == harness), None)
        if entry is None:
            raise WorkspaceError(f"harness {harness} is not probed")
        return dict(entry["capabilities"])

    def validate_agent(self, agent: Agent) -> None:
        harness = canonical_harness(agent.harness)
        entry = next((item for item in self._catalog if item["harness"] == harness), None)
        if entry is None:
            raise WorkspaceError(f"unsupported harness: {agent.harness}")
        if harness != "custom" and not entry["found"]:
            raise WorkspaceError(f"{harness} CLI is not installed")
        if harness == "custom":
            command = getattr(agent, "command", [])
            extra = getattr(agent, "extra_args", [])
            if not isinstance(command, list) or not isinstance(extra, list) or (*command, *extra) not in self._custom_cache:
                raise WorkspaceError("custom harness command must be probed before creating an agent")
            entry = self._custom_cache[(*command, *extra)]
        if agent.model and agent.model not in {m["id"] for m in entry["models"]}:
            raise WorkspaceError(f"model {agent.model} is not offered by {harness}")
        if agent.allowed_tools:
            if not entry["capabilities"]["allowed_tools"]:
                raise WorkspaceError(f"{harness} cannot enforce allowed_tools")
            unknown = set(agent.allowed_tools) - {tool["id"] for tool in entry["tools"]}
            if unknown:
                raise WorkspaceError(f"unsupported tools for {harness}: {', '.join(sorted(unknown))}")
        allowed_flags = {"claude": {"--max-turns", "--max-budget-usd"},
                         "gemini": set(), "codex": set(), "custom": set()}
        extra = getattr(agent, "extra_args", [])
        if not isinstance(extra, list) or any(not isinstance(part, str) or not part or "\x00" in part for part in extra):
            raise WorkspaceError("extra_args must be an argv array")
        if harness == "custom":
            if any(part.startswith("--lgt-") for part in extra):
                raise WorkspaceError("unsafe or unsupported extra_args for custom")
            return
        i = 0
        while i < len(extra):
            flag = extra[i]
            if flag not in allowed_flags[harness] or i + 1 >= len(extra) or extra[i + 1].startswith("-"):
                raise WorkspaceError(f"unsafe or unsupported extra_args for {harness}")
            if flag == "--max-turns" and (not extra[i + 1].isdigit() or int(extra[i + 1]) <= 0):
                raise WorkspaceError("--max-turns must be a positive integer")
            if flag == "--max-budget-usd":
                try:
                    value = float(extra[i + 1])
                except ValueError as exc:
                    raise WorkspaceError("--max-budget-usd must be positive and finite") from exc
                if not math.isfinite(value) or value <= 0:
                    raise WorkspaceError("--max-budget-usd must be positive and finite")
            i += 2

    def runner(self, harness: str):
        name = canonical_harness(harness)
        kwargs = dict(tool_output_cap=self.settings.tool_output_cap,
                      line_limit=self.settings.ndjson_line_limit,
                      cancel_grace_seconds=self.settings.cancel_grace_seconds,
                      log_dir=self.settings.log_dir)
        if name == "codex":
            return CodexAppServerRunner(**kwargs, codex_bin=self.codex_bin,
                startup_timeout_seconds=self.settings.router_timeout_seconds)
        if name == "claude":
            return ClaudeRunner(self.claude_command, **kwargs)
        if name == "gemini":
            return GeminiRunner(self.gemini_command, **kwargs)
        if name == "custom":
            return CustomRunner((), **kwargs)
        raise WorkspaceError(f"unsupported harness: {harness}")

    def artifact_exists(self, harness: str, sid: str, cwd: str) -> bool:
        name = canonical_harness(harness)
        if name == "codex":
            return CodexAppServerRunner.artifact_exists(sid, cwd)
        if not sid or not cwd or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sid):
            return False
        if name == "claude":
            target = Path(cwd).resolve()
            for path in (Path.home() / ".claude" / "projects").rglob(f"{sid}.jsonl"):
                try:
                    with path.open("r", encoding="utf-8") as stream:
                        for _, line in zip(range(20), stream):
                            if len(line) > 65536:
                                continue
                            record = json.loads(line)
                            if record.get("cwd") and Path(record["cwd"]).resolve() == target:
                                return True
                except (OSError, ValueError, TypeError):
                    continue
            return False
        if name == "gemini":
            target = Path(cwd).resolve()
            roots = [target, *(parent for parent in target.parents if (parent / ".git").exists())]
            for root in roots:
                project_hash = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
                chats = Path.home() / ".gemini" / "tmp" / project_hash / "chats"
                if not chats.is_dir():
                    continue
                for path in chats.glob("session-*.json"):
                    try:
                        if path.stat().st_size > 32 * 1024 * 1024:
                            continue
                        if json.loads(path.read_text(encoding="utf-8")).get("sessionId") == sid:
                            return True
                    except (OSError, ValueError):
                        continue
            return False
        return False
