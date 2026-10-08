from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .codex_adapter import CodexAppServerRunner, bundled_codex_binary
from .config import Settings
from .gateway import create_app
from .locking import RuntimeLock
from .oneshot import make_cli_invoker
from .orchestrator import Orchestrator
from .router import CLIRouter
from .store import Store
from .summarizer import CLISummarizer


@dataclass(frozen=True)
class RuntimeConfig:
    settings: Settings
    checkpoint_mode: str
    codex_bin: str | None = None
    claude_command: tuple[str, ...] = ("claude",)
    codex_router_command: tuple[str, ...] | None = None


def load_config(path: str | Path) -> RuntimeConfig:
    """Require explicit values for the spec's unresolved runtime settings."""
    config_path = Path(path).resolve()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("settings"), dict):
        raise ValueError("configuration must contain a settings object")
    unknown = set(raw) - {"settings", "checkpoint_mode", "codex_bin", "claude_command", "codex_router_command"}
    if unknown:
        raise ValueError(f"unknown configuration fields: {', '.join(sorted(unknown))}")
    values = dict(raw["settings"])
    # The user's override supersedes the spec's hold-until-active-runs-finish rule.
    if "route_after_active" in values:
        raise ValueError("route_after_active is fixed to false for this workspace")
    values["route_after_active"] = False
    expected = {field.name for field in fields(Settings)}
    missing, extras = expected - values.keys(), values.keys() - expected
    if missing or extras:
        raise ValueError(f"settings fields missing={sorted(missing)}, unknown={sorted(extras)}")
    directory = Path(values["data_dir"]).expanduser()
    if not directory.is_absolute():
        directory = config_path.parent / directory
    values["data_dir"] = directory.resolve()
    mode = raw.get("checkpoint_mode")
    if mode not in {"cli", "deferred"}:
        raise ValueError("checkpoint_mode must explicitly be cli or deferred")
    commands: dict[str, tuple[str, ...] | None] = {}
    for name in ("claude_command", "codex_router_command"):
        value = raw.get(name, ["claude"] if name == "claude_command" else None)
        if value is not None and (not isinstance(value, list) or not value
                                  or any(not isinstance(part, str) or not part for part in value)):
            raise ValueError(f"{name} must be a nonempty argv array")
        commands[name] = tuple(value) if value is not None else None
    binary = raw.get("codex_bin")
    if binary is not None and (not isinstance(binary, str) or not binary):
        raise ValueError("codex_bin must be a path string or null")
    return RuntimeConfig(Settings(**values), mode, binary, **commands)


class BackendRuntime:
    """Open SQLite on the server thread and own its process-wide lifetime."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.settings = config.settings
        self.human_id = "local"
        self._orch: Orchestrator | None = None
        self._store: Store | None = None
        self._lock = RuntimeLock(self.settings.data_dir / "workspace.lock")
        self.harness_info: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        if self._orch is None:
            raise RuntimeError("backend runtime has not started")
        return getattr(self._orch, name)

    async def start(self) -> None:
        if self._orch is not None:
            return
        self._lock.acquire()
        try:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            self._store = Store(self.settings.database_path)
            runner_args = dict(
                tool_output_cap=self.settings.tool_output_cap,
                line_limit=self.settings.ndjson_line_limit,
                cancel_grace_seconds=self.settings.cancel_grace_seconds,
                log_dir=self.settings.log_dir,
                codex_bin=self.config.codex_bin,
                startup_timeout_seconds=self.settings.router_timeout_seconds,
            )
            self.harness_info = await CodexAppServerRunner(**runner_args).probe()
            binary = bundled_codex_binary(self.config.codex_bin)
            claude = list(self.config.claude_command)
            claude[0] = shutil.which(claude[0]) or claude[0]
            cli_args = dict(
                claude_command=claude,
                codex_command=list(self.config.codex_router_command or (binary,)),
                cwd=str(self.settings.data_dir), timeout_seconds=self.settings.router_timeout_seconds,
                attempts=self.settings.router_attempts, claude_model=self.settings.router_model,
                codex_model=self.settings.codex_router_model,
                invoke=make_cli_invoker(output_limit_bytes=self.settings.ndjson_line_limit),
            )
            def runner_factory(harness: str):
                if harness != "codex":
                    raise ValueError("only Codex app-server is supported in this milestone")
                return CodexAppServerRunner(**runner_args)

            self._orch = Orchestrator(
                self._store, self.settings, CLIRouter(**cli_args), runner_factory,
                lambda harness, sid, cwd: harness == "codex" and CodexAppServerRunner.artifact_exists(sid, cwd),
                human_id=self.human_id,
                summarizer=CLISummarizer(**cli_args) if self.config.checkpoint_mode == "cli" else None,
            )
            await self._orch.start()
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        try:
            if self._orch is not None:
                await self._orch.close()
        finally:
            self._orch = None
            if self._store is not None:
                self._store.close()
                self._store = None
            self._lock.close()


def application(config_path: str | Path):
    return create_app(BackendRuntime(load_config(config_path)))
