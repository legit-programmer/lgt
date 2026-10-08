from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime choices supplied explicitly by the application's entry point."""

    data_dir: Path
    max_hops: int
    tool_output_cap: int
    concurrent_runs: int
    replay_cap: int
    router_timeout_seconds: float
    router_context_events: int
    route_after_active: bool
    session_ttl_seconds: float | None
    router_model: str
    codex_router_model: str | None
    router_attempts: int
    ndjson_line_limit: int
    cancel_grace_seconds: float
    checkpoint_threshold: int
    checkpoint_tail_chars: int
    checkpoint_summary_chars: int
    attachment_max_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.data_dir, Path) or not self.data_dir.is_absolute():
            raise ValueError("data_dir must be an absolute Path")
        for name in (
            "tool_output_cap", "concurrent_runs", "replay_cap", "router_context_events",
            "router_attempts", "ndjson_line_limit", "checkpoint_threshold",
            "checkpoint_tail_chars", "checkpoint_summary_chars", "attachment_max_bytes",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if type(self.max_hops) is not int or self.max_hops < 0:
            raise ValueError("max_hops must be nonnegative")
        for name in ("router_timeout_seconds", "cancel_grace_seconds", "session_ttl_seconds"):
            value = getattr(self, name)
            if value is None and name == "session_ttl_seconds":
                continue
            if type(value) not in (int, float):
                raise ValueError(f"{name} must be a number")
        if self.router_timeout_seconds <= 0 or self.cancel_grace_seconds < 0:
            raise ValueError("invalid timeout or cancellation grace period")
        if self.session_ttl_seconds is not None and self.session_ttl_seconds <= 0:
            raise ValueError("session TTL must be positive or None")
        if self.checkpoint_tail_chars >= self.checkpoint_threshold:
            raise ValueError("checkpoint tail must be smaller than checkpoint threshold")
        if type(self.route_after_active) is not bool:
            raise ValueError("route_after_active must be boolean")
        if not isinstance(self.router_model, str) or not self.router_model:
            raise ValueError("router_model must be nonempty")
        if self.codex_router_model is not None and (
            not isinstance(self.codex_router_model, str) or not self.codex_router_model
        ):
            raise ValueError("codex_router_model must be nonempty or null")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "workspace.sqlite3"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def attachment_dir(self) -> Path:
        return self.data_dir / "attachments"
