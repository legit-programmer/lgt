from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from urllib.parse import urlsplit


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
    allowed_origins: tuple[str, ...] = ()
    attachment_channel_quota_bytes: int = 262144000
    attachment_retention_seconds: float = 86400
    thumbnail_max_dimension: int = 512

    def __post_init__(self) -> None:
        if not isinstance(self.data_dir, Path) or not self.data_dir.is_absolute():
            raise ValueError("data_dir must be an absolute Path")
        for name in (
            "tool_output_cap", "concurrent_runs", "replay_cap", "router_context_events",
            "router_attempts", "ndjson_line_limit", "checkpoint_threshold",
            "checkpoint_tail_chars", "checkpoint_summary_chars", "attachment_max_bytes",
            "attachment_channel_quota_bytes", "thumbnail_max_dimension",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if type(self.max_hops) is not int or self.max_hops < 0:
            raise ValueError("max_hops must be nonnegative")
        for name in ("router_timeout_seconds", "cancel_grace_seconds", "session_ttl_seconds", "attachment_retention_seconds"):
            value = getattr(self, name)
            if value is None and name == "session_ttl_seconds":
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if self.router_timeout_seconds <= 0 or self.cancel_grace_seconds < 0:
            raise ValueError("invalid timeout or cancellation grace period")
        if self.session_ttl_seconds is not None and self.session_ttl_seconds <= 0:
            raise ValueError("session TTL must be positive or None")
        if self.attachment_retention_seconds <= 0:
            raise ValueError("attachment_retention_seconds must be positive")
        if not isinstance(self.allowed_origins, (tuple, list)):
            raise ValueError("allowed_origins must be an array of exact origins")
        for origin in self.allowed_origins:
            if (not isinstance(origin, str) or not origin or origin in {"*", "null"}
                    or any(ord(char) < 33 for char in origin)):
                raise ValueError("allowed_origins must contain exact non-opaque origins")
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https", "tauri", "file"}
                    or parsed.path or parsed.query or parsed.fragment
                    or parsed.username is not None or parsed.password is not None
                    or (parsed.scheme != "file" and not parsed.hostname)
                    or (parsed.scheme == "file" and origin != "file://")):
                raise ValueError(f"invalid allowed origin: {origin!r}")
            try:
                parsed.port
            except ValueError:
                raise ValueError(f"invalid allowed origin: {origin!r}") from None
        object.__setattr__(self, "allowed_origins", tuple(dict.fromkeys(self.allowed_origins)))
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
