from __future__ import annotations

import html
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .models import Agent, Channel, Event, Session, SessionMode

if TYPE_CHECKING:
    from .store import Store


def render_delta(
    store: Store, agent_id: str, channel_id: str,
    from_seq: int, to_seq: int, mode: SessionMode,
) -> str:
    """Render exactly the requested log range, with edits visible at to_seq."""
    channel = store.get_channel(channel_id)
    all_events = store.events(channel_id, to_seq=to_seq)
    edits: dict[int, dict] = {}
    for event in all_events:
        if event.kind == "message_edit":
            target = event.payload["target_seq"]
            edits.setdefault(target, {}).update(event.payload)

    selected = [event for event in all_events if from_seq <= event.seq <= to_seq]
    tools: dict[str, Counter[str]] = {}
    for event in selected:
        if event.kind == "tool_call" and not (
            mode == "resume" and event.author_id == agent_id
        ):
            key = event.run_id or f"author:{event.author_id}"
            tools.setdefault(key, Counter())[str(event.payload.get("name", "tool"))] += 1

    handles = {agent.agent_id: agent.handle for agent in store.list_agents()}
    lines: list[str] = []
    emitted_tools: set[str] = set()
    for event in selected:
        label = event.payload.get("author_handle", handles.get(event.author_id, event.author_id))
        if event.kind == "message":
            if mode == "resume" and event.author_kind == "agent" and event.author_id == agent_id:
                continue
            edit = edits.get(event.seq, {})
            if edit.get("deleted", False):
                continue
            text = edit.get("text", event.payload.get("text", ""))
            lines.append(f"[{label}] {text}")
            for attachment in event.payload.get("attachments", ()):
                lines.append(_attachment_line(store, attachment))
        elif event.kind == "tool_call":
            key = event.run_id or f"author:{event.author_id}"
            if key not in tools or key in emitted_tools:
                continue
            emitted_tools.add(key)
            counts = tools[key]
            names = ", ".join(
                f"{name} x{count}" if count > 1 else name
                for name, count in sorted(counts.items())
            )
            lines.append(f"[{label}] (ran {sum(counts.values())} tools: {names})")
        elif event.kind == "system":
            lines.append(f"[system] {event.payload.get('text', '')}")
        elif event.kind == "cwd_changed":
            lines.append(f"[system] The channel working directory is now {event.payload['cwd']}")
        elif event.kind == "member_added":
            lines.append(f"[system] {event.payload['handle']} joined the channel")
        elif event.kind == "member_removed":
            lines.append(f"[system] {event.payload['handle']} left the channel")

    name = html.escape(channel.name, quote=True)
    return f'<channel name="{name}" new_since="{from_seq - 1}">\n' + "\n".join(lines) + "\n</channel>"


def _attachment_line(store: Store, attachment: dict) -> str:
    # The payload keeps metadata only; the stored path is resolved at render
    # time so the log never depends on where the data directory lives.
    try:
        path = store.get_attachment(attachment["attachment_id"]).path
    except KeyError:
        path = "unavailable"
    return (f"  (attached {attachment['filename']}, {attachment['media_type']}, "
            f"{attachment['size_bytes']} bytes, at {path})")


def rendered_contribution(event: Event) -> int:
    """Count prompt content, excluding raw tool output and bookkeeping."""
    if event.kind == "message":
        return len(f"[{event.author_id}] {event.payload.get('text', '')}\n")
    if event.kind == "tool_call":
        return len(f"[{event.author_id}] (tool: {event.payload.get('name', 'tool')})\n")
    if event.kind == "system":
        return len(f"[system] {event.payload.get('text', '')}\n")
    return 0


@dataclass(frozen=True)
class SessionPlan:
    mode: SessionMode
    start_seq: int
    session: Session | None
    summary: str | None


def resolve_session(
    store: Store,
    agent: Agent,
    channel: Channel,
    end_seq: int,
    artifact_exists: Callable[[str, str], bool],
    ttl_seconds: float | None,
) -> SessionPlan:
    session = store.get_session(agent.agent_id, channel.channel_id)
    events = store.events(channel.channel_id, to_seq=end_seq)
    if session is not None:
        valid = (
            session.last_run_status == "clean"
            and session.harness == agent.harness
            and session.config_fingerprint == agent.fingerprint()
            and session.cwd == channel.cwd
            and session.last_seen_seq <= end_seq
            and bool(session.harness_session_id)
        )
        if valid:
            valid = artifact_exists(session.harness_session_id, channel.cwd)
        if valid and ttl_seconds is not None:
            last_used = datetime.fromisoformat(session.last_used_at)
            valid = (datetime.now(timezone.utc) - last_used).total_seconds() <= ttl_seconds
        if valid:
            valid = not any(
                event.seq > session.last_seen_seq
                and (
                    event.kind == "context_reset"
                    or (event.kind == "message_edit"
                        and event.payload["target_seq"] <= session.last_seen_seq)
                )
                for event in events
            )
        if valid:
            return SessionPlan("resume", session.last_seen_seq + 1, session, None)

    return cold_plan(events)


def cold_plan(events: list[Event]) -> SessionPlan:
    end_seq = max((e.seq for e in events), default=0)
    reset_seq = max((e.seq for e in events if e.kind == "context_reset"), default=0)
    checkpoints = [
        e for e in events
        if e.kind == "context_checkpoint"
        and reset_seq <= e.payload.get("covers_through_seq", -1) <= end_seq
        and e.seq > reset_seq
        and not any(
            edit.kind == "message_edit"
            and edit.seq > e.seq
            and edit.payload["target_seq"] <= e.payload["covers_through_seq"]
            for edit in events
        )
    ]
    if checkpoints:
        checkpoint = max(checkpoints, key=lambda e: e.seq)
        return SessionPlan(
            "cold", checkpoint.payload["covers_through_seq"] + 1,
            None, checkpoint.payload["summary"],
        )
    return SessionPlan("cold", reset_seq + 1, None, None)


def rendered_size(store: Store, channel_id: str, from_seq: int, to_seq: int) -> int:
    rendered = render_delta(store, "", channel_id, from_seq, to_seq, "cold")
    return len(rendered.split("\n", 1)[1].rsplit("\n", 1)[0])


def render_turn(
    store: Store, agent: Agent, channel: Channel, plan: SessionPlan, end_seq: int,
) -> str:
    delta = render_delta(
        store, agent.agent_id, channel.channel_id, plan.start_seq, end_seq, plan.mode,
    )
    if plan.summary:
        return f"<context_checkpoint>\n{plan.summary}\n</context_checkpoint>\n{delta}"
    return delta
