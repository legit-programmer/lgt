from __future__ import annotations

import html
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .models import Agent, Channel, Event, Session, SessionMode
from .replies import render_reply

if TYPE_CHECKING:
    from .store import Store


def render_tool_summary(counts: dict[str, int]) -> str:
    names = ", ".join(
        f"{name} x{count}" if count > 1 else name
        for name, count in sorted(counts.items())
    )
    return f"(ran {sum(counts.values())} tools: {names})"


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
            tools.setdefault(key, Counter())[str(event.payload.get("tool", event.payload.get("name", "tool")))] += 1

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
            lines.append(f"[{label}] {render_reply(event.payload.get('reply'))}{text}")
            for attachment in event.payload.get("attachments", ()):
                lines.append(_attachment_line(store, attachment))
        elif event.kind == "tool_call":
            key = event.run_id or f"author:{event.author_id}"
            if key not in tools or key in emitted_tools:
                continue
            emitted_tools.add(key)
            counts = tools[key]
            lines.append(f"[{label}] {render_tool_summary(counts)}")
        elif event.kind == "tool_summary":
            if mode != "resume" or event.author_id != agent_id:
                lines.append(f"[{label}] {render_tool_summary(event.payload['tools'])}")
        elif event.kind == "system":
            lines.append(f"[system] {event.payload.get('text', '')}")
        elif event.kind == "cwd_changed":
            lines.append(f"[system] The channel working directory is now {event.payload['cwd']}")
        elif event.kind == "member_added":
            lines.append(f"[system] {event.payload['handle']} joined the channel")
        elif event.kind == "member_removed":
            lines.append(f"[system] {event.payload['handle']} left the channel")
        elif event.kind == "ownership_changed":
            lines.append(f"[system] Channel ownership assigned to {event.payload.get('primary_handle', event.payload['primary_agent_id'])}")
        elif event.kind == "agent_transfer":
            lines.append(f"[system] {event.payload['mode']} {event.payload['status']}: "
                         f"{event.payload['source']} to {', '.join(event.payload['targets'])}")

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
        return len(f"[{event.author_id}] (tool: {event.payload.get('tool', event.payload.get('name', 'tool'))})\n")
    if event.kind == "tool_summary":
        return len(f"[{event.author_id}] {render_tool_summary(event.payload['tools'])}\n")
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
    # Native CLI sessions retain intermediate text and raw tools. A quiet turn
    # must rebuild from the user-visible log rather than inherit that history.
    if not channel.focus_mode:
        return cold_plan(events)
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
                    or (event.kind == "channel_changed" and "focus_mode" in event.payload)
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
    delivery_seqs: tuple[int, ...] = (),
) -> str:
    delta = render_delta(
        store, agent.agent_id, channel.channel_id, plan.start_seq, end_seq, plan.mode,
    )
    if plan.summary:
        delta = f"<context_checkpoint>\n{plan.summary}\n</context_checkpoint>\n{delta}"
    if not channel.focus_mode:
        delta = (
            "<response_mode>\n"
            "Work autonomously until the assigned task is complete or you need the user's input. "
            "Return the completed result, or ask the necessary question as your final reply. "
            "Omit progress narration. Include any delegation or handoff in your final reply.\n"
            "</response_mode>\n" + delta
        )
    if channel.kind == "dm":
        return delta
    members = {m["member_id"] for m in store.members(channel.channel_id) if m["member_kind"] == "agent"}
    roster = [{"agent_id": a.agent_id, "handle": a.handle, "description": a.description}
              for a in store.list_agents() if a.agent_id in members]
    state = {"primary_agent_id": channel.primary_agent_id, "ownership_version": channel.ownership_version,
             "allow_handoff": channel.allow_handoff,
             **store.routing_state(channel.channel_id), "agents": roster}
    edits: dict[int, dict] = {}
    for event in store.events(channel.channel_id, to_seq=end_seq):
        if event.kind == "message_edit":
            edits.setdefault(event.payload["target_seq"], {}).update(event.payload)
    state["assigned_messages"] = [
        {"seq": seq, "author_id": message.author_id,
         "text": edits.get(seq, {}).get("text", message.payload.get("text", "")),
         **({"reply": message.payload["reply"]} if message.payload.get("reply") else {}),
         "transfer": message.payload.get("transfer"),
         "transfers": message.payload.get("transfers", [])}
        for seq in delivery_seqs if seq >= plan.start_seq and not edits.get(seq, {}).get("deleted")
        for message in [store.get_event(channel.channel_id, seq)]
    ]
    instructions = (
        "You are a member of this channel. Handle requests within your capabilities. "
        "The backend owns channel-wide conversation ownership. Task completion never changes it. "
        "For work requiring another listed agent, include <@agent_id:delegation> in your message, "
        "followed by the task and relevant context. Use the exact agent_id from the roster. "
        "For example: I reviewed the request. <@agent_id:handoff> Please implement the change. "
        "The backend processes these markers only after the message is complete. "
        "You may delegate to multiple agents in one message, but request at most one handoff. "
        "Each recipient receives the full message. Code examples do not trigger transfers. "
        "Delegation keeps the primary owner; ordinary @mentions also delegate. "
        "When another agent assigns you work through a handoff, delegation, or direct mention, "
        "report back to that requesting agent when you finish or become blocked. "
        "Identify the requester from the assigned message's author_id, not the current primary. "
        "Send the result in a completed channel message containing <@requester_agent_id:delegation>, "
        "replacing requester_agent_id with the requester's exact agent_id from the roster. "
        "Put the marker in normal prose, outside code or quotes, so the requester is actually pinged; "
        "an unaddressed channel update does not deliver the result to them. "
        "Include the original task, outcome, changed paths, validation, and any blockers or next steps. "
        "This report-back rule applies equally to handoffs and delegations; use delegation for the "
        "result so reporting back does not itself change channel ownership. "
        "If further work or clarification is needed from another agent, explicitly ping that agent again. "
        "A completion report or acknowledgment is not a new task: do not ping back merely to acknowledge it. "
        "Only send another ping when there is actionable follow-up, to avoid notification loops. "
        "Only the current primary may use <@agent_id:handoff> when allow_handoff is true, "
        "to transfer the user's task and ownership. The receiver accepts when its harness starts the turn. "
        "If this turn receives a handoff, you become primary at turn start unless a newer selection superseded it. "
        "If handoff is disabled, delegate. Do not execute tasks outside your capabilities. "
        "Include relevant paths, decisions, constraints, and attachment references in the transfer text. "
        "Use only agents in the roster. Act on assigned_messages; other channel messages provide background.\n"
    )
    return f"<channel_routing>\n{instructions}{json.dumps(state, ensure_ascii=False)}\n</channel_routing>\n{delta}"
