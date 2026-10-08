from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lgt.attachments import AttachmentTooLarge
from lgt.gateway import _event_payload
from lgt.models import Agent, Run, WorkspaceError
from lgt.orchestrator import Orchestrator
from lgt.run_errors import normalize_error
from lgt.store import Store
from tests.support import ControlledFactory, FakeRouter, eventually, settings


@pytest.fixture
async def workspace(tmp_path):
    store = Store(tmp_path / "workspace.sqlite")
    factory = ControlledFactory()
    router = FakeRouter(["alpha"])
    orch = Orchestrator(store, settings(tmp_path), router, factory, lambda *args: True, human_id="local")
    for name in ("alpha", "beta"):
        orch.put_agent(Agent(name, name, name.title(), f"{name} specialist", "codex", "", "help"))
    channel = orch.create_channel("general", agent_ids=["alpha"])
    await orch.start()
    try:
        yield orch, store, factory, router, channel
    finally:
        await orch.close()
        store.close()


def frames(subscription):
    collected = []
    while not subscription.queue.empty():
        collected.append(subscription.queue.get_nowait())
    return collected


@pytest.mark.asyncio
async def test_agent_identity_auto_dm_and_retirement_stop_future_deliveries(workspace):
    orch, store, factory, _, channel = workspace
    original = store.get_agent("alpha")
    assert original.dm_channel_id and store.get_channel(original.dm_channel_id).kind == "dm"
    assert original.avatar["seed"] == "alpha"
    assert (original.hue, store.get_agent("beta").hue) == (0, 1)
    orch.put_agent(replace(original, name="Renamed", hue=7))
    renamed = store.get_agent("alpha")
    assert (renamed.avatar, renamed.hue, renamed.dm_channel_id) == (original.avatar, 0, original.dm_channel_id)
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    await orch.send_message(channel.channel_id, "later", ["alpha"])
    retired = await orch.retire_agent("alpha")
    assert retired.retired_at
    assert factory.started[0].cancelled and len(factory.started) == 1
    assert [agent.agent_id for agent in store.list_agents()] == ["beta"]
    assert store.get_channel(original.dm_channel_id).archived_at
    assert not orch.queue_items(channel.channel_id)
    with pytest.raises(WorkspaceError, match="retired"):
        orch.add_member(channel.channel_id, "alpha")
    with pytest.raises(WorkspaceError, match="retired"):
        await orch.unarchive_channel(original.dm_channel_id)


@pytest.mark.asyncio
async def test_unsupported_resume_and_failed_agent_creation_leave_consistent_state(workspace):
    orch, store, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "first", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].finish()
    await eventually(lambda: not store.list_runs(channel.channel_id, active_only=True))
    catalog = next(item for item in orch.harness_registry._catalog if item["harness"] == "codex")
    catalog["capabilities"]["resume"] = False
    assert orch.context_stats(channel.channel_id)["mode"] == "cold"
    await orch.send_message(channel.channel_id, "second", ["alpha"])
    await eventually(lambda: len(factory.started) == 2)
    assert factory.started[1].turn.run.session_mode == "cold"
    subscription = orch.bus.subscribe({channel.channel_id}, 1000)
    original = store.set_agent_dm_channel
    def fail_dm(*args):
        raise RuntimeError("failed midway")
    store.set_agent_dm_channel = fail_dm
    with pytest.raises(RuntimeError, match="midway"):
        orch.put_agent(Agent("new", "new", "New", "helper", "codex", "", "help"))
    store.set_agent_dm_channel = original
    with pytest.raises(KeyError):
        store.get_agent("new")
    assert frames(subscription) == []
    orch.bus.unsubscribe(subscription)


@pytest.mark.asyncio
async def test_routing_records_mentions_and_suggests_outside_members(workspace):
    orch, store, factory, router, channel = workspace
    message = await orch.send_message(channel.channel_id, "work", ["alpha"])
    decision = next(event for event in store.events(channel.channel_id) if event.kind == "routing_decision")
    assert decision.payload == {"for_seqs": [message.seq], "agents": ["alpha"], "suggested_agents": [],
                                "method": "mention", "reason_code": "mention", "reason": "explicit mentions"}
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].finish()
    await eventually(lambda: not store.list_runs(channel.channel_id, active_only=True))
    router.picks = ["beta"]
    outside = await orch.send_message(channel.channel_id, "need beta expertise")
    await eventually(lambda: any(event.kind == "routing_decision" and outside.seq in event.payload["for_seqs"]
                                 for event in store.events(channel.channel_id)))
    result = [event for event in store.events(channel.channel_id) if event.kind == "routing_decision"][-1]
    assert result.payload["agents"] == [] and result.payload["suggested_agents"] == ["beta"]
    assert result.payload["reason_code"] == "none"
    assert len(factory.started) == 1
    assert next(entry for entry in router.calls[-1].roster if entry["agent_id"] == "beta")["in_channel"] is False


@pytest.mark.asyncio
async def test_live_status_usage_context_and_cross_window_read_state(workspace):
    orch, store, factory, _, channel = workspace
    first = orch.bus.subscribe({channel.channel_id}, 1000)
    second = orch.bus.subscribe({channel.channel_id}, 1000)
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    runner = factory.started[0]
    runner.emit("tool_call", tool_call_id="tool-1", tool="bash", label="Bash", summary="pnpm lint", input={})
    await eventually(lambda: orch.agent_statuses()[0]["activity"] is not None)
    assert orch.agent_statuses()[0]["state"] == "working"
    assert orch.agent_statuses()[0]["activity"]["summary"] == "pnpm lint"
    runner.emit("usage", tokens_in=100, tokens_out=20, tokens_cached_in=30, tokens_reasoning=5,
                tokens_total=120, context_tokens=800, model_context_window=200000)
    runner.emit("limits", primary={"usedPercent": 25, "resetsAt": 123}, planType="plus")
    runner.finish("done")
    await eventually(lambda: store.get_run(runner.turn.run.run_id).status == "completed")
    run = store.get_run(runner.turn.run.run_id)
    assert (run.tokens_in, run.tokens_out, run.tokens_cached_in, run.tokens_reasoning, run.tokens_total) == (100, 20, 30, 5, 120)
    assert "cost_usd" not in run.__dataclass_fields__
    context = orch.context_stats(channel.channel_id, "alpha")
    assert context["mode"] == "resume" and context["context_tokens"] == 800
    assert context["model_context_window"] == 200000 and context["messages_in_context"] == 2
    summary = store.channel_summary(channel.channel_id, "local")
    assert summary["unread_count"] == 1 and summary["preview"]["text_excerpt"] == "done"
    await orch.mark_read(channel.channel_id, store.get_channel(channel.channel_id).next_seq - 1)
    for subscription in (first, second):
        output = frames(subscription)
        assert any(frame["type"] == "agent_status" and frame["state"] == "working" for frame in output)
        assert any(frame["type"] == "usage" and frame.get("tokens_total") == 120 for frame in output)
        assert any(frame["type"] == "channel_summary" and frame["unread_count"] == 0 for frame in output)
    assert store.get_harness_limits("codex")["planType"] == "plus"
    await orch.new_context(channel.channel_id)
    reset = orch.context_stats(channel.channel_id)
    assert reset["mode"] == "cold" and reset["context_tokens"] is None and reset["messages_in_context"] == 0
    orch.bus.unsubscribe(first)
    orch.bus.unsubscribe(second)


@pytest.mark.asyncio
async def test_run_failure_has_server_written_text_and_structured_error(workspace):
    orch, store, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    runner = factory.started[0]
    runner.emit("run_finished", ok=False, error={"code": "oom", "message": "out of memory"}, exit_code=137)
    await eventually(lambda: store.get_run(runner.turn.run.run_id).status == "failed")
    run = store.get_run(runner.turn.run.run_id)
    terminal = [event for event in store.events(channel.channel_id) if event.kind == "run_status"][-1]
    assert terminal.payload["agent_id"] == "alpha"
    assert terminal.payload["started_at"] and terminal.payload["ended_at"] and run.duration_ms >= 0
    assert terminal.payload["error"]["code"] == "oom" and terminal.payload["error"]["exit_code"] == 137
    assert terminal.payload["text"].startswith("codex exited 137 (out of memory) after")
    assert orch.agent_statuses()[0]["last_failure"]["run_id"] == run.run_id
    assert normalize_error("terminated", 137)["code"] == "harness"
    assert normalize_error({"message": "Process failed", "exit_code": None}, 42)["exit_code"] == 42


@pytest.mark.asyncio
async def test_legacy_lifecycle_is_upgraded_without_editing_the_event_log(workspace):
    orch, store, _, _, channel = workspace
    trigger = store.append_event(channel.channel_id, "message", "human", "local", {"text": "old request"})
    store.create_run(Run("legacy", channel.channel_id, "alpha", trigger.seq, 1, trigger.seq, "cold", "codex",
                         channel.cwd, status="failed", error="timed out", exit_code=1,
                         started_at="2026-10-01T00:00:00+00:00", ended_at="2026-10-01T00:00:05+00:00"))
    event = store.append_event(channel.channel_id, "run_status", "system", "system",
                               {"run_id": "legacy", "status": "failed", "error": "timed out"},
                               run_id="legacy", chain_id=trigger.chain_id)
    response = _event_payload(event, store)["payload"]
    assert response["agent_id"] == "alpha" and response["duration_ms"] == 5000
    assert response["error"]["code"] == "timeout"
    assert "after 5s" in response["text"]
    assert store.get_event(channel.channel_id, event.seq).payload["error"] == "timed out"


async def chunks(value):
    yield value


@pytest.mark.asyncio
async def test_concurrent_upload_quota_and_retention_keep_sent_files(workspace):
    orch, store, _, _, channel = workspace
    orch.settings = replace(orch.settings, attachment_channel_quota_bytes=5)
    results = await asyncio.gather(
        orch.create_attachment(channel.channel_id, "first.txt", "text/plain", chunks(b"abc")),
        orch.create_attachment(channel.channel_id, "second.txt", "text/plain", chunks(b"def")),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AttachmentTooLarge) for result in results) == 1
    sent = next(result for result in results if not isinstance(result, BaseException))
    await orch.send_message(channel.channel_id, "keep", ["alpha"], [sent.attachment_id])
    unsent = await orch.create_attachment(channel.channel_id, "stale.txt", "text/plain", chunks(b"xy"))
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    store.conn.execute("UPDATE attachments SET created_at=? WHERE attachment_id=?", (yesterday, unsent.attachment_id))
    assert orch.cleanup_attachments() == 1
    assert not Path(unsent.path).exists() and Path(sent.path).exists()
    assert store.attachment_channel_bytes(channel.channel_id) == 3


@pytest.mark.asyncio
async def test_bootstrap_is_atomic_and_commands_and_suggestions_are_server_owned(workspace):
    orch, store, _, router, channel = workspace
    catalog = next(item for item in orch.harness_registry._catalog if item["harness"] == "codex")
    catalog["models"] = [{"id": "fixture", "label": "Fixture", "description": "Test", "default": True}]
    subscription = orch.bus.subscribe({channel.channel_id}, 1000)
    before = len(store.list_agents())
    Path(channel.cwd).mkdir(parents=True, exist_ok=True)
    with pytest.raises(WorkspaceError, match="unavailable"):
        await orch.bootstrap(["coder", "missing"], channel.cwd)
    original = store.set_agent_dm_channel
    def fail_dm(*args):
        raise RuntimeError("failed midway")
    store.set_agent_dm_channel = fail_dm
    with pytest.raises(RuntimeError, match="midway"):
        await orch.bootstrap(["coder", "docs"], channel.cwd)
    store.set_agent_dm_channel = original
    assert len(store.list_agents()) == before and frames(subscription) == []
    result = await orch.bootstrap(["coder", "docs"], channel.cwd)
    assert result["channel"]["name"] == "general" and len(result["agents"]) == 2
    assert all(agent["dm_channel_id"] for agent in result["agents"])
    assert any(frame["type"] == "agent" for frame in frames(subscription))
    target = orch.settings.data_dir / "different directory"
    target.mkdir()
    cwd_event = await orch.send_message(channel.channel_id, f"/cwd {target}")
    assert cwd_event.kind == "cwd_changed" and store.get_channel(channel.channel_id).cwd == str(target)
    assert (await orch.send_message(channel.channel_id, "/new")).kind == "context_reset"
    assert (await orch.send_message(channel.channel_id, "/cancel")).payload["code"] == "cancel"
    calls = []
    async def suggest(roster):
        calls.append(roster)
        return ["Review the project", "Plan the change", "Update the docs"]
    router.suggestions = suggest
    assert len(await orch.channel_suggestions(channel.channel_id)) == 3
    await orch.channel_suggestions(channel.channel_id)
    assert len(calls) == 1
    orch.put_agent(replace(store.get_agent("alpha"), description="new work"))
    await orch.channel_suggestions(channel.channel_id)
    assert len(calls) == 2
    profile = await orch.update_profile("Local user")
    assert profile == store.get_human_profile("local")
    assert any(frame["type"] == "me" and frame["display_name"] == "Local user" for frame in frames(subscription))
    orch.bus.unsubscribe(subscription)
