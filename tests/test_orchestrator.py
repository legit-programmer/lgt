from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from lgt.models import Agent, Run, Session, WorkspaceError
from lgt.orchestrator import Orchestrator
from lgt.context import render_delta
from lgt.store import Store
from tests.support import ControlledFactory, FakeRouter, eventually, settings


@pytest.fixture
async def workspace(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    router = FakeRouter(["alpha"])
    orch = Orchestrator(store, settings(tmp_path), router, factory,
                        lambda harness, sid, cwd: True, human_id="local")
    for name in ["alpha", "beta"]:
        orch.put_agent(Agent(name, name, name, name + " specialist", "codex", "", "help"))
    channel = orch.create_channel("test", agent_ids=["alpha", "beta"])
    await orch.start()
    yield orch, store, factory, router, channel
    await orch.close()
    store.close()


@pytest.mark.asyncio
async def test_busy_agent_messages_coalesce_without_advancing_to_current_max(workspace):
    orch, store, factory, _, channel = workspace
    first = await orch.send_message(channel.channel_id, "first", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    runner = factory.started[0]
    second = await orch.send_message(channel.channel_id, "second", ["alpha"])
    third = await orch.send_message(channel.channel_id, "third", ["alpha"])
    assert len(factory.started) == 1
    assert len(store.queue(channel.channel_id, "awaiting_agent")) == 2
    assert store.get_session("alpha", channel.channel_id) is None
    runner.finish()
    await eventually(lambda: len(factory.started) == 2)
    session = store.get_session("alpha", channel.channel_id)
    assert session.last_seen_seq == runner.turn.run.delta_end_seq
    assert session.last_seen_seq >= first.seq
    assert session.last_seen_seq < third.seq
    turn = factory.started[1].turn
    assert turn.run.trigger_seq == third.seq
    assert turn.run.session_mode == "resume"
    assert "second" in turn.prompt and "third" in turn.prompt
    assert "[alpha] done" not in turn.prompt
    assert second.seq <= turn.run.delta_end_seq


@pytest.mark.asyncio
async def test_unmentioned_message_routes_immediately_and_selects_busy_agent(workspace):
    orch, store, factory, router, channel = workspace
    await orch.send_message(channel.channel_id, "start", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    routed = await orch.send_message(channel.channel_id, "more work")
    await eventually(lambda: bool(router.calls) and bool(store.queue(channel.channel_id, "awaiting_agent")))
    assert len(factory.started) == 1
    assert next(a for a in router.calls[0].roster if a["agent_id"] == "alpha")["busy"]
    assert store.queue(channel.channel_id, "awaiting_agent")[0].event_seq == routed.seq
    factory.started[0].finish()
    await eventually(lambda: len(factory.started) == 2)
    assert "more work" in factory.started[1].turn.prompt


@pytest.mark.asyncio
async def test_idle_other_agent_runs_in_parallel_and_mentions_bypass_router(workspace):
    orch, _, factory, router, channel = workspace
    await orch.send_message(channel.channel_id, "alpha work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    await orch.send_message(channel.channel_id, "beta work", ["beta"])
    await eventually(lambda: len(factory.started) == 2)
    assert {r.turn.agent.agent_id for r in factory.started} == {"alpha", "beta"}
    assert not router.calls


@pytest.mark.asyncio
async def test_rendered_author_handle_is_saved_in_the_immutable_log(workspace):
    orch, store, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].finish()
    await eventually(lambda: store.get_session("alpha", channel.channel_id) is not None)
    end = store.get_channel(channel.channel_id).next_seq - 1
    before = render_delta(store, "", channel.channel_id, 1, end, "cold")
    orch.put_agent(replace(store.get_agent("alpha"), handle="renamed"))
    assert render_delta(store, "", channel.channel_id, 1, end, "cold") == before


@pytest.mark.asyncio
async def test_reset_during_run_forces_cold_from_reset(workspace):
    orch, _, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "old instruction", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    await orch.new_context(channel.channel_id)
    await orch.send_message(channel.channel_id, "new instruction", ["alpha"])
    factory.started[0].finish()
    await eventually(lambda: len(factory.started) == 2)
    assert factory.started[1].turn.run.session_mode == "cold"
    assert "old instruction" not in factory.started[1].turn.prompt
    assert "new instruction" in factory.started[1].turn.prompt


@pytest.mark.asyncio
async def test_edit_seen_message_invalidates_session_and_does_not_rewrite_log(workspace):
    orch, store, factory, _, channel = workspace
    original = await orch.send_message(channel.channel_id, "original", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].finish()
    await eventually(lambda: store.get_session("alpha", channel.channel_id) is not None)
    await orch.edit_message(channel.channel_id, original.seq, "replacement")
    await orch.send_message(channel.channel_id, "continue", ["alpha"])
    await eventually(lambda: len(factory.started) == 2)
    assert store.get_event(channel.channel_id, original.seq).payload["text"] == "original"
    assert factory.started[1].turn.run.session_mode == "cold"
    assert "replacement" in factory.started[1].turn.prompt
    assert "original" not in factory.started[1].turn.prompt


@pytest.mark.asyncio
async def test_partial_deltas_are_live_and_cancel_commits_one_terminal(workspace):
    orch, store, factory, _, channel = workspace
    subscription = orch.bus.subscribe({channel.channel_id}, 100)
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    runner = factory.started[0]
    runner.emit("text_delta", text="partial")
    await eventually(lambda: bool(orch.partial_snapshots({channel.channel_id})))
    assert orch.partial_snapshots({channel.channel_id})[0]["text"] == "partial"
    assert all(e.kind != "text_delta" for e in store.events(channel.channel_id))
    await orch.cancel_run(runner.turn.run.run_id)
    assert store.get_run(runner.turn.run.run_id).status == "cancelled"
    statuses = [e.payload["status"] for e in store.events(channel.channel_id) if e.kind == "run_status"]
    assert statuses.count("cancelled") == 1
    assert not orch.partial_snapshots({channel.channel_id})
    orch.bus.unsubscribe(subscription)


@pytest.mark.asyncio
async def test_cancel_queued_before_execute_starts(workspace):
    orch, store, factory, _, channel = workspace
    await orch._semaphore.acquire()
    await orch._semaphore.acquire()
    await orch._semaphore.acquire()
    await orch._semaphore.acquire()
    await orch.send_message(channel.channel_id, "queued", ["alpha"])
    run = store.list_runs(channel.channel_id, active_only=True)[0]
    await orch.cancel_run(run.run_id)
    assert store.get_run(run.run_id).status == "cancelled"
    assert not factory.started
    for _ in range(4):
        orch._semaphore.release()


@pytest.mark.asyncio
async def test_dm_bypasses_router_and_has_one_agent(workspace):
    orch, _, factory, router, _ = workspace
    dm = orch.create_channel("dm", kind="dm", agent_ids=["alpha"])
    await orch.send_message(dm.channel_id, "hello")
    await eventually(lambda: len(factory.started) == 1)
    assert factory.started[0].turn.agent.agent_id == "alpha"
    assert not router.calls
    with pytest.raises(WorkspaceError):
        orch.add_member(dm.channel_id, "beta")


@pytest.mark.asyncio
async def test_unsupported_codex_tool_scope_is_not_silently_ignored(workspace):
    orch, store, _, _, _ = workspace
    agent = replace(store.get_agent("alpha"), allowed_tools=["Read"])
    with pytest.raises(WorkspaceError, match="cannot enforce"):
        orch.put_agent(agent)


@pytest.mark.asyncio
async def test_hop_limit_stops_agent_loop_without_router(workspace):
    orch, store, factory, router, channel = workspace
    origin = await orch.send_message(channel.channel_id, "begin", ["alpha"])
    for count, target in enumerate(["beta", "alpha", "beta", "alpha"]):
        await eventually(lambda count=count: len(factory.started) == count + 1)
        factory.started[count].finish(f"@{target} continue")
    await eventually(lambda: any(e.kind == "system" and e.payload.get("code") == "max_hops"
                                 for e in store.events(channel.channel_id)))
    assert len(factory.started) == 4
    agent_messages = [e for e in store.events(channel.channel_id) if e.author_kind == "agent"]
    assert [e.hop for e in agent_messages] == [0, 1, 2, 3]
    assert {e.chain_id for e in agent_messages} == {origin.id}
    assert not router.calls


@pytest.mark.asyncio
async def test_orphan_recovery_marks_dirty_then_replays_durable_queue(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    orch = Orchestrator(store, settings(tmp_path), FakeRouter(), factory,
                        lambda *args: True, human_id="local")
    agent = Agent("alpha", "alpha", "alpha", "specialist", "codex", "", "help")
    orch.put_agent(agent)
    channel = orch.create_channel("test", agent_ids=["alpha"])
    first = store.append_event(channel.channel_id, "message", "human", "local", {"text": "old", "mentions": []})
    store.create_run(Run("orphan", channel.channel_id, "alpha", first.seq, 1, 1, "cold", "codex", channel.cwd, status="running"))
    store.put_session(Session("alpha", channel.channel_id, "codex", "sid", channel.cwd, 1, agent.fingerprint(), "clean"))
    second = store.append_event(channel.channel_id, "message", "human", "local", {"text": "queued", "mentions": []})
    store.enqueue(channel.channel_id, second.seq, "alpha")
    await orch.start()
    await eventually(lambda: len(factory.started) == 1)
    assert store.get_run("orphan").error["code"] == "orphaned"
    assert store.get_session("alpha", channel.channel_id).last_run_status == "dirty"
    assert factory.started[0].turn.run.session_mode == "cold"
    assert "queued" in factory.started[0].turn.prompt
    assert not store.queue(channel.channel_id, "awaiting_agent")
    await orch.close()
    store.close()


@pytest.mark.asyncio
async def test_completed_session_is_dirtied_by_subsequent_failed_turn(workspace):
    orch, store, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "first", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].finish()
    await eventually(lambda: store.get_session("alpha", channel.channel_id) is not None)
    await orch.send_message(channel.channel_id, "second", ["alpha"])
    await eventually(lambda: len(factory.started) == 2)
    factory.started[1].finish(ok=False)
    await eventually(lambda: store.get_session("alpha", channel.channel_id).last_run_status == "dirty")
    await orch.send_message(channel.channel_id, "third", ["alpha"])
    await eventually(lambda: len(factory.started) == 3)
    assert factory.started[2].turn.run.session_mode == "cold"
