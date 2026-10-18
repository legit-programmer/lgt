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
    startup_timeout_seconds: float
    checkpoint_timeout_seconds: float
    session_ttl_seconds: float | None
    checkpoint_claude_model: str
    checkpoint_codex_model: str | None
    checkpoint_attempts: int
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
    listen_host: str = "127.0.0.1"
    listen_port: int = 8000
    advertised_url: str | None = None

    def __post_init__(self) -> None:
        # Wildcard IPv4 also keeps loopback available for host administration.
        if not isinstance(self.listen_host, str) or self.listen_host not in {"127.0.0.1", "0.0.0.0"}:
            raise ValueError("listen_host must be 127.0.0.1 or 0.0.0.0")
        if type(self.listen_port) is not int or not 0 <= self.listen_port <= 65535:
            raise ValueError("listen_port must be an integer between 0 and 65535")
        if self.advertised_url is not None:
            object.__setattr__(self, "advertised_url", connection_origin(self.advertised_url))
        if not isinstance(self.data_dir, Path) or not self.data_dir.is_absolute():
            raise ValueError("data_dir must be an absolute Path")
        for name in (
            "tool_output_cap", "concurrent_runs", "replay_cap", "checkpoint_attempts",
            "ndjson_line_limit", "checkpoint_threshold",
            "checkpoint_tail_chars", "checkpoint_summary_chars", "attachment_max_bytes",
            "attachment_channel_quota_bytes", "thumbnail_max_dimension",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if type(self.max_hops) is not int or self.max_hops < 0:
            raise ValueError("max_hops must be nonnegative")
        for name in (
            "startup_timeout_seconds", "checkpoint_timeout_seconds", "cancel_grace_seconds",
            "session_ttl_seconds", "attachment_retention_seconds",
        ):
            value = getattr(self, name)
            if value is None and name == "session_ttl_seconds":
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if self.startup_timeout_seconds <= 0 or self.checkpoint_timeout_seconds <= 0 or self.cancel_grace_seconds < 0:
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
        if not isinstance(self.checkpoint_claude_model, str) or not self.checkpoint_claude_model:
            raise ValueError("checkpoint_claude_model must be nonempty")
        if self.checkpoint_codex_model is not None and (
            not isinstance(self.checkpoint_codex_model, str) or not self.checkpoint_codex_model
        ):
            raise ValueError("checkpoint_codex_model must be nonempty or null")

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


def connection_origin(value: str) -> str:
    """A pairing address is an HTTP(S) origin, never a URL containing secrets."""
    if not isinstance(value, str) or any(ord(char) < 33 for char in value):
        raise ValueError("advertised_url must be an HTTP(S) origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.hostname in {"0.0.0.0", "::", "*"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or port == 0 or "\\" in value):
            raise ValueError
    except ValueError:
        raise ValueError("advertised_url must be a reachable HTTP(S) origin without credentials or a path") from None
    return value.rstrip("/")
