from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from lgt.models import Agent, Run, Session, WorkspaceError
from lgt.orchestrator import Orchestrator
from lgt.context import render_delta
from lgt.replies import REPLY_QUOTE_MAX_CHARS
from lgt.store import Store
from tests.support import ControlledFactory, eventually, settings


@pytest.fixture
async def workspace(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    orch = Orchestrator(store, settings(tmp_path), factory,
                        lambda harness, sid, cwd: True, human_id="local")
    for name in ["alpha", "beta"]:
        orch.put_agent(Agent(name, name, name, name + " specialist", "codex", "", "help"))
    channel = orch.create_channel("test", agent_ids=["alpha", "beta"], primary_agent_id="alpha")
    channel = store.patch_channel(channel.channel_id, focus_mode=True)
    await orch.start()
    yield orch, store, factory, channel
    await orch.close()
    store.close()


def append_reply_source(store, channel, text):
    question = store.append_event(channel.channel_id, "message", "human", "local", {"text": "question"})
    return store.append_event(channel.channel_id, "message", "agent", "beta",
                              {"text": text, "author_handle": "beta"}, chain_id=question.chain_id)


@pytest.mark.asyncio
async def test_reply_targets_author_and_includes_text_only_after_context_reset(workspace):
    orch, store, factory, channel = workspace
    source = append_reply_source(store, channel, "Use this approach. @alpha")
    store.append_event(channel.channel_id, "tool_call", "agent", "beta",
                       {"tool_call_id": "read", "name": "Read", "input": {"path": "private"}},
                       chain_id=source.chain_id)
    store.append_event(channel.channel_id, "tool_result", "agent", "beta",
                       {"tool_call_id": "read", "output": "RAW TOOL OUTPUT"}, chain_id=source.chain_id)
    await orch.new_context(channel.channel_id)
    reply = await orch.send_message(channel.channel_id, "explain that", reply_to_seq=source.seq)
    await eventually(lambda: len(factory.started) == 1)
    assert reply.payload["mentions"] == ["beta"]
    assert reply.payload["text"] == "explain that"
    assert reply.payload["reply"]["text"] == "Use this approach. @alpha"
    assert store.get_channel(channel.channel_id).primary_agent_id == "beta"
    turn = factory.started[0].turn
    assert turn.agent.agent_id == "beta"
    assert '"reply":' in turn.prompt  # assigned_messages carries the quote too
    assert "Use this approach. @alpha" in turn.prompt and "explain that" in turn.prompt
    assert "RAW TOOL OUTPUT" not in turn.prompt and "private" not in turn.prompt
    resumed = render_delta(store, "beta", channel.channel_id, reply.seq, reply.seq, "resume")
    assert "Use this approach. @alpha" in resumed and "Actual reply: explain that" in resumed


@pytest.mark.asyncio
async def test_reply_selection_and_explicit_mentions_override_author(workspace):
    orch, store, factory, channel = workspace
    source = append_reply_source(store, channel, "Choose **option B**. @beta")
    reply = await orch.send_message(channel.channel_id, "@alpha implement this", reply_to_seq=source.seq,
                                    reply_selection="option B")
    await eventually(lambda: len(factory.started) == 1)
    assert reply.payload["mentions"] == ["alpha"]
    assert factory.started[0].turn.agent.agent_id == "alpha"
    assert reply.payload["reply"]["text"] == "option B"
    assert reply.payload["reply"]["selected"] is True
    explicit = await orch.send_message(channel.channel_id, "handle this", mentions=["alpha"], reply_to_seq=source.seq)
    assert explicit.payload["mentions"] == ["alpha"]
    bounded = orch.preview_reply(channel.channel_id, source.seq, "B" * (REPLY_QUOTE_MAX_CHARS + 1))
    assert len(bounded["text"]) == REPLY_QUOTE_MAX_CHARS and bounded["text"].endswith("truncated..")


@pytest.mark.asyncio
async def test_reply_snapshot_uses_current_edit_is_bounded_and_does_not_nest_quotes(workspace):
    orch, store, _, channel = workspace
    source = store.append_event(channel.channel_id, "message", "human", "local",
                                {"text": "old", "reply": {"text": "NESTED QUOTE"}})
    await orch.edit_message(channel.channel_id, source.seq, text="x" * (REPLY_QUOTE_MAX_CHARS + 1))
    preview = orch.preview_reply(channel.channel_id, source.seq)
    assert len(preview["text"]) == REPLY_QUOTE_MAX_CHARS
    assert preview["text"].endswith("truncated..") and preview["truncated"] is True
    reply = await orch.send_message(channel.channel_id, "why?", reply_to_seq=source.seq)
    assert reply.payload["reply"] == preview
    assert reply.payload["mentions"] == []  # human-message replies use ordinary routing
    await orch.edit_message(channel.channel_id, source.seq, text="later edit")
    assert store.get_event(channel.channel_id, reply.seq).payload["reply"] == preview
    assert "NESTED QUOTE" not in str(reply.payload)
    assert orch.preview_reply(channel.channel_id, source.seq)["text"] == "later edit"
    exact_cap = orch.preview_reply(channel.channel_id, source.seq, "x" * REPLY_QUOTE_MAX_CHARS)
    assert exact_cap["truncated"] is False and len(exact_cap["text"]) == REPLY_QUOTE_MAX_CHARS


@pytest.mark.asyncio
async def test_invalid_reply_creates_no_message_or_delivery(workspace):
    orch, store, _, channel = workspace
    source = store.append_event(channel.channel_id, "message", "human", "local", {"text": "gone"})
    await orch.edit_message(channel.channel_id, source.seq, deleted=True)
    tool = store.append_event(channel.channel_id, "tool_result", "agent", "alpha",
                              {"tool_call_id": "read", "output": "tool only"}, chain_id=source.chain_id)
    end = store.get_channel(channel.channel_id).next_seq
    for seq, selection, error in [(source.seq, None, WorkspaceError), (tool.seq, None, WorkspaceError),
                                   (999, None, KeyError), (None, "excerpt", WorkspaceError),
                                   (tool.seq, "   ", WorkspaceError), (0, None, WorkspaceError)]:
        with pytest.raises(error):
            await orch.send_message(channel.channel_id, "reply", reply_to_seq=seq, reply_selection=selection)
    assert store.get_channel(channel.channel_id).next_seq == end
    assert store.queue(channel.channel_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["removed", "retired"])
async def test_reply_to_unavailable_agent_fails_instead_of_routing_elsewhere(workspace, unavailable):
    orch, store, _, channel = workspace
    source = append_reply_source(store, channel, "answer")
    if unavailable == "removed":
        store.remove_member(channel.channel_id, "agent", "beta")
    else:
        store.retire_agent("beta")
    with pytest.raises(WorkspaceError, match="no longer available"):
        await orch.send_message(channel.channel_id, "reply", reply_to_seq=source.seq)


@pytest.mark.asyncio
async def test_reply_text_that_looks_like_a_command_is_sent_as_a_reply(workspace):
    orch, store, factory, channel = workspace
    source = append_reply_source(store, channel, "Try /new")
    reply = await orch.send_message(channel.channel_id, "/new", reply_to_seq=source.seq)
    await eventually(lambda: len(factory.started) == 1)
    assert reply.kind == "message" and reply.payload["text"] == "/new"


@pytest.mark.asyncio
async def test_busy_agent_messages_coalesce_without_advancing_to_current_max(workspace):
    orch, store, factory, channel = workspace
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
async def test_unmentioned_message_queues_to_busy_primary(workspace):
    orch, store, factory, channel = workspace
    await orch.send_message(channel.channel_id, "start", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    routed = await orch.send_message(channel.channel_id, "more work")
    await eventually(lambda: bool(store.queue(channel.channel_id, "awaiting_agent")))
    assert len(factory.started) == 1
    assert store.get_channel(channel.channel_id).primary_agent_id == "alpha"
    assert store.queue(channel.channel_id, "awaiting_agent")[0].event_seq == routed.seq
    factory.started[0].finish()
    await eventually(lambda: len(factory.started) == 2)
    assert "more work" in factory.started[1].turn.prompt


@pytest.mark.asyncio
async def test_idle_other_agent_runs_in_parallel_with_explicit_mentions(workspace):
    orch, _, factory, channel = workspace
    await orch.send_message(channel.channel_id, "alpha work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    await orch.send_message(channel.channel_id, "beta work", ["beta"])
    await eventually(lambda: len(factory.started) == 2)
    assert {r.turn.agent.agent_id for r in factory.started} == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_rendered_author_handle_is_saved_in_the_immutable_log(workspace):
    orch, store, factory, channel = workspace
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
    orch, _, factory, channel = workspace
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
    orch, store, factory, channel = workspace
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
    orch, store, factory, channel = workspace
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
    orch, store, factory, channel = workspace
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
async def test_dm_dispatches_to_its_one_agent(workspace):
    orch, _, factory, _ = workspace
    dm = orch.create_channel("dm", kind="dm", agent_ids=["alpha"], primary_agent_id="alpha")
    await orch.send_message(dm.channel_id, "hello")
    await eventually(lambda: len(factory.started) == 1)
    assert factory.started[0].turn.agent.agent_id == "alpha"
    with pytest.raises(WorkspaceError):
        orch.add_member(dm.channel_id, "beta")


@pytest.mark.asyncio
async def test_unsupported_codex_tool_scope_is_not_silently_ignored(workspace):
    orch, store, _, _ = workspace
    agent = replace(store.get_agent("alpha"), allowed_tools=["Read"])
    with pytest.raises(WorkspaceError, match="cannot enforce"):
        orch.put_agent(agent)


@pytest.mark.asyncio
async def test_hop_limit_stops_agent_loop(workspace):
    orch, store, factory, channel = workspace
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


@pytest.mark.asyncio
async def test_orphan_recovery_marks_dirty_then_replays_durable_queue(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    orch = Orchestrator(store, settings(tmp_path), factory,
                        lambda *args: True, human_id="local")
    agent = Agent("alpha", "alpha", "alpha", "specialist", "codex", "", "help")
    orch.put_agent(agent)
    channel = orch.create_channel("test", agent_ids=["alpha"], primary_agent_id="alpha")
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
    orch, store, factory, channel = workspace
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
