from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lgt.models import Channel, Event, RoutingRequest
from lgt.router import CLIRouter


BUSY = {"agent_id": "a-busy", "handle": "builder", "description": "Writes code", "busy": True}
IDLE = {"agent_id": "a-idle", "handle": "researcher", "description": "Researches topics", "busy": False}


def request(roster=None) -> RoutingRequest:
    return RoutingRequest(
        channel=Channel(channel_id="c1", kind="channel", name="general", cwd=".", cwd_managed=True),
        roster=list(roster if roster is not None else [BUSY, IDLE]),
        context="Earlier, the user asked for a backend implementation.",
        messages=[Event(
            id=1,
            channel_id="c1",
            seq=1,
            ts="2026-10-07T00:00:00+00:00",
            kind="message",
            author_kind="human",
            author_id="human-1",
            run_id=None,
            chain_id=1,
            hop=0,
            payload={"text": "Please add a parser", "mentions": []},
        )],
    )


def router(invoke, *, attempts=1, choice=None) -> CLIRouter:
    kwargs = {}
    if choice is not None:
        kwargs["choice"] = choice
    return CLIRouter(
        claude_command=["claude"],
        codex_command=["codex"],
        cwd=".",
        timeout_seconds=3.0,
        attempts=attempts,
        claude_model="haiku",
        codex_model="gpt-5-codex",
        invoke=invoke,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_claude_routes_to_busy_agent_and_accepts_json_wrapper():
    calls = []

    async def invoke(argv, cwd, prompt, timeout):
        calls.append((argv, cwd, prompt, timeout))
        assert "\"busy\":true" in prompt
        assert "messages" in prompt and "Earlier, the user asked" in prompt
        assert argv[:2] == ["claude", "-p"]
        assert argv[argv.index("--model") + 1] == "haiku"
        assert argv[argv.index("--tools") + 1] == ""
        assert "--no-session-persistence" in argv
        assert "--dangerously-skip-permissions" in argv
        return json.dumps({
            "type": "result",
            "is_error": False,
            "structured_output": {"agents": ["a-busy", "a-busy"], "reason": "Code change."},
        })

    decision = await router(invoke).route(request())

    assert decision.agents == ["a-busy"]
    assert decision.reason == "Code change."
    assert decision.error is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_empty_claude_selection_is_valid_and_does_not_call_codex():
    async def invoke(argv, cwd, prompt, timeout):
        return json.dumps({"result": json.dumps({"agents": [], "reason": "No response needed."})})

    decision = await router(invoke).route(request())

    assert decision.agents == []
    assert decision.reason == "No response needed."
    assert decision.error is None


@pytest.mark.asyncio
async def test_router_can_suggest_an_agent_outside_the_channel():
    async def invoke(argv, cwd, prompt, timeout):
        assert '"in_channel":false' in prompt
        return json.dumps({"agents": [], "suggested_agents": ["a-idle"], "reason": "Add a researcher."})
    decision = await router(invoke).route(request([{**IDLE, "in_channel": False}]))
    assert decision.agents == [] and decision.suggested_agents == ["a-idle"]
    assert decision.reason_code == "none"


@pytest.mark.asyncio
async def test_random_fallback_never_selects_an_outside_agent():
    async def invoke(*args):
        raise TimeoutError("offline")
    decision = await router(invoke).route(request([{**IDLE, "in_channel": False}]))
    assert decision.agents == [] and decision.reason_code == "none"


@pytest.mark.asyncio
async def test_starter_suggestions_use_router_model_with_their_own_schema():
    async def invoke(argv, cwd, prompt, timeout):
        schema = json.loads(argv[argv.index("--json-schema") + 1])
        assert schema["required"] == ["suggestions"]
        assert "haiku" in argv and '"description": "Writes code"' in prompt
        return json.dumps({"structured_output": {"suggestions": ["Review the code", "Plan a change", "Write tests"]}})
    assert await router(invoke).suggestions([{"name": "Coder", "description": "Writes code"}]) == [
        "Review the code", "Plan a change", "Write tests",
    ]


@pytest.mark.asyncio
async def test_invalid_claude_selection_falls_through_to_codex():
    calls = []

    async def invoke(argv, cwd, prompt, timeout):
        calls.append(argv)
        if argv[0] == "claude":
            return json.dumps({"agents": ["not-on-roster"], "reason": "Unknown."})
        return json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps({"agents": ["a-idle"], "reason": "Research."})},
        }) + '\n' + json.dumps({"type": "turn.completed"})

    decision = await router(invoke).route(request())

    assert decision.agents == ["a-idle"]
    assert decision.reason == "Research."
    assert decision.error and "claude 1/1" in decision.error
    assert [argv[0] for argv in calls] == ["claude", "codex"]


@pytest.mark.asyncio
async def test_claude_retries_after_timeout_before_accepting_success():
    calls = 0

    async def invoke(argv, cwd, prompt, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("timed out")
        return json.dumps({"agents": ["a-busy"], "reason": "Retry succeeded."})

    decision = await router(invoke, attempts=2).route(request())

    assert calls == 2
    assert decision.agents == ["a-busy"]
    assert decision.error is None


@pytest.mark.asyncio
async def test_codex_uses_ephemeral_schema_file_and_removes_it(tmp_path, monkeypatch):
    # Keep the assertion independent of the process temp directory while still
    # proving the schema exists during invocation and is removed afterward.
    monkeypatch.setattr("lgt.router.tempfile.tempdir", str(tmp_path))
    schema_paths = []

    async def invoke(argv, cwd, prompt, timeout):
        assert argv[:2] == ["codex", "exec"]
        assert "--ephemeral" in argv
        assert "--json" in argv
        assert "--skip-git-repo-check" in argv
        assert "--dangerously-bypass-approvals-and-sandbox" in argv
        assert "--sandbox" not in argv
        assert argv[argv.index("-m") + 1] == "gpt-5-codex"
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        schema_paths.append(schema_path)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        assert argv[-1] == "-"
        return json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps({"agents": [], "reason": "No specialist."})},
        }) + '\n' + json.dumps({"type": "turn.completed"})

    # Claude exhausts its one attempt, which activates Codex.
    async def claude_then_codex(argv, cwd, prompt, timeout):
        if argv[0] == "claude":
            raise RuntimeError("Claude unavailable")
        return await invoke(argv, cwd, prompt, timeout)

    decision = await router(claude_then_codex).route(request())

    assert decision.agents == []
    assert decision.error and "Claude unavailable" in decision.error
    assert len(schema_paths) == 1
    assert not schema_paths[0].exists()


@pytest.mark.asyncio
async def test_both_clis_failing_randomly_selects_a_busy_roster_member():
    async def invoke(argv, cwd, prompt, timeout):
        raise RuntimeError(f"{argv[0]} unavailable")

    decision = await router(
        invoke,
        choice=lambda roster: roster[0],
    ).route(request())

    assert decision.agents == ["a-busy"]
    assert "randomly selected @builder" in decision.reason
    assert decision.error and "claude" in decision.error and "codex" in decision.error


@pytest.mark.asyncio
async def test_empty_roster_returns_nobody_without_a_model_call():
    async def invoke(argv, cwd, prompt, timeout):
        pytest.fail("an empty roster must not invoke a CLI")

    decision = await router(invoke, choice=lambda _: pytest.fail("choice must not run")).route(
        request(roster=[]),
    )

    assert decision.agents == []
    assert "no agents" in decision.reason
    assert decision.error is None


@pytest.mark.asyncio
async def test_cancellation_propagates_without_trying_fallback():
    calls = []

    async def invoke(argv, cwd, prompt, timeout):
        calls.append(argv[0])
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await router(invoke).route(request())

    assert calls == ["claude"]
