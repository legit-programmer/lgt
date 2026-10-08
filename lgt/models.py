from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

Harness = Literal["claude", "claude_code", "codex", "gemini", "custom"]
SessionMode = Literal["resume", "cold"]
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
EVENT_KINDS = frozenset({
    "message", "tool_call", "tool_result", "run_status", "routing_decision",
    "context_reset", "context_checkpoint", "message_edit", "system",
    "cwd_changed", "member_added", "member_removed", "delivery_cancelled",
    "channel_changed", "agent_retired",
})
PENDING_QUEUE_STATES = frozenset({"awaiting_route", "awaiting_agent"})


# DiceBear style for agents that don't choose one. Critters is CC0 (no attribution).
DEFAULT_AVATAR_STYLE = "critters"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    """Generate a Crockford base32 ULID without a runtime dependency."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars: list[str] = []
    for _ in range(26):
        chars.append(alphabet[value & 31])
        value >>= 5
    return "".join(reversed(chars))


@dataclass(frozen=True)
class Agent:
    agent_id: str
    handle: str
    name: str
    description: str
    harness: Harness
    model: str
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)
    default_cwd: str | None = None
    permission_mode: str = "bypass"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    avatar: dict[str, str] = field(default_factory=dict)
    hue: int = -1
    extra_args: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    retired_at: str | None = None
    dm_channel_id: str | None = None

    def __post_init__(self) -> None:
        if not self.avatar:
            object.__setattr__(self, "avatar", {"style": DEFAULT_AVATAR_STYLE, "seed": self.agent_id})
        elif not self.avatar.get("seed"):
            object.__setattr__(self, "avatar", {**self.avatar, "seed": self.agent_id})

    def fingerprint(self) -> str:
        config = {
            "harness": self.harness, "model": self.model,
            "system_prompt": self.system_prompt, "tools": sorted(self.allowed_tools),
            "extra_args": self.extra_args, "command": self.command,
            "permission_mode": self.permission_mode,
        }
        return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Channel:
    channel_id: str
    kind: Literal["channel", "dm"]
    name: str
    cwd: str
    cwd_managed: bool
    next_seq: int = 1
    rendered_chars_since_checkpoint: int = 0
    created_at: str = field(default_factory=utc_now)
    archived_at: str | None = None


@dataclass(frozen=True)
class Event:
    id: int
    channel_id: str
    seq: int
    ts: str
    kind: str
    author_kind: str
    author_id: str
    run_id: str | None
    chain_id: int
    hop: int
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Run:
    run_id: str
    channel_id: str
    agent_id: str
    trigger_seq: int
    delta_start_seq: int
    delta_end_seq: int
    session_mode: SessionMode
    harness: Harness
    cwd: str
    harness_session_id: str | None = None
    pgid: int | None = None
    status: str = "queued"
    error: dict[str, Any] | str | None = None
    exit_code: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached_in: int = 0
    tokens_cache_creation: int = 0
    tokens_reasoning: int = 0
    tokens_total: int = 0
    model_context_window: int | None = None
    context_tokens: int | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class Session:
    agent_id: str
    channel_id: str
    harness: Harness
    harness_session_id: str | None
    cwd: str
    last_seen_seq: int
    config_fingerprint: str
    last_run_status: Literal["clean", "dirty"]
    last_used_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class QueueItem:
    queue_id: int
    channel_id: str
    event_seq: int
    agent_id: str | None
    wait_for: list[str]
    state: str
    created_at: str


@dataclass(frozen=True)
class Attachment:
    attachment_id: str
    channel_id: str
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    path: str
    message_seq: int | None = None
    created_at: str = field(default_factory=utc_now)

    def summary(self) -> dict[str, Any]:
        """Metadata captured in a message payload; the path stays server-side."""
        return {
            "attachment_id": self.attachment_id, "filename": self.filename,
            "media_type": self.media_type, "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class Turn:
    run: Run
    agent: Agent
    channel: Channel
    prompt: str
    session: Session | None
    # Files attached to the messages that triggered this turn. Adapters pass
    # images the harness can view as native inputs; the prompt names every file.
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class NormalizedEvent:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingRequest:
    channel: Channel
    roster: list[dict[str, Any]]
    context: str
    messages: list[Event]


@dataclass(frozen=True)
class RoutingDecision:
    agents: list[str]
    reason: str
    error: str | None = None
    suggested_agents: list[str] = field(default_factory=list)
    reason_code: str = "router"


class Router(Protocol):
    async def route(self, request: RoutingRequest) -> RoutingDecision: ...


class Runner(Protocol):
    def start(self, turn: Turn) -> AsyncIterator[NormalizedEvent]: ...

    async def cancel(self, reason: str) -> None: ...


RunnerFactory = Callable[[Harness], Runner]


class WorkspaceError(ValueError):
    """Invalid workspace command, safe to report to a client."""
