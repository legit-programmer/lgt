from __future__ import annotations

import json

import pytest

from lgt import artefacts
from lgt.models import Agent
from lgt.orchestrator import Orchestrator
from lgt.store import Store
from tests.support import ControlledFactory, eventually, settings


@pytest.fixture
async def workspace(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    orch = Orchestrator(store, settings(tmp_path), factory, lambda *args: True, human_id="local")
    for name in ("alpha", "beta"):
        orch.put_agent(Agent(name, name, name, "specialist", "codex", "", "help"))
    channel = orch.create_channel("test", agent_ids=["alpha", "beta"], primary_agent_id="alpha")
    await orch.start()
    yield orch, store, factory, channel.channel_id
    await orch.close()
    store.close()


def drain(subscription):
    result = []
    while not subscription.queue.empty():
        result.append(subscription.queue.get_nowait())
    return result


def messages(store, cid):
    return [e.payload["text"] for e in store.events(cid) if e.kind == "message" and e.author_kind == "agent"]


async def start(orch, factory, cid, text="Do the task", agent="alpha"):
    count = len(factory.started)
    await orch.send_message(cid, text, [agent])
    await eventually(lambda: len(factory.started) == count + 1)
    return factory.started[-1]


async def finish(store, runner, text="done"):
    runner.finish(text)
    await eventually(lambda: store.get_run(runner.turn.run.run_id).status == "completed")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["channel", "dm"])
async def test_quiet_output_is_never_logged_streamed_replayed_or_given_to_next_turn(workspace, kind):
    orch, store, factory, cid = workspace
    if kind == "dm":
        cid = store.get_agent("alpha").dm_channel_id
    assert store.get_channel(cid).focus_mode is False
    subscription = orch.bus.subscribe({cid}, 1000)
    runner = await start(orch, factory, cid)
    assert runner.turn.run.session_mode == "cold"
    runner.emit("message", text="hidden commentary", phase="commentary")
    runner.emit("message", text="hidden progress")
    runner.emit("text_delta", text="hidden streamed text")
    for i in range(2):
        runner.emit("tool_call", tool="read", tool_call_id=str(i), input={"path": "FOCUS_PRIVATE_PATH"},
                    summary="FOCUS_PRIVATE_SUMMARY")
        runner.emit("tool_result", tool_call_id=str(i), output="FOCUS_PRIVATE_OUTPUT")
    runner.emit("message", text="The completed result", phase="final_answer")
    runner.emit("usage", tokens_in=123)
    await eventually(lambda: store.get_run(runner.turn.run.run_id).tokens_in == 123)
    assert messages(store, cid) == []
    assert orch.partial_snapshots({cid}) == []
    live_frames = drain(subscription)
    assert not any(f["type"] == "delta" for f in live_frames)
    assert "hidden" not in json.dumps(live_frames) and "FOCUS_PRIVATE_" not in json.dumps(live_frames)
    await finish(store, runner, "")
    assert messages(store, cid) == ["The completed result"]
    summaries = [e for e in store.events(cid) if e.kind == "tool_summary"]
    assert len(summaries) == 1
    assert summaries[0].payload == {"author_handle": "alpha", "tools": {"read": 2}, "total": 2}
    assert not any(e.kind in {"tool_call", "tool_result"} for e in store.events(cid))
    assert store.get_session("alpha", cid).last_run_status == "dirty"
    retained = json.dumps([e.to_dict() for e in store.replay(0, [cid], 1000)] + live_frames + drain(subscription)
                          + orch.snapshot_frames({cid}))
    assert "hidden" not in retained and "FOCUS_PRIVATE_" not in retained
    assert store.search("hidden", channel_id=cid)["messages"] == []
    followup = await start(orch, factory, cid, "Continue")
    assert followup.turn.run.session_mode == "cold" and followup.turn.session is None
    assert "The completed result" in followup.turn.prompt
    assert "(ran 2 tools: read x2)" in followup.turn.prompt
    assert "hidden" not in followup.turn.prompt and "FOCUS_PRIVATE_" not in followup.turn.prompt
    if kind == "channel":
        peer = await start(orch, factory, cid, "Review the completed work", agent="beta")
        assert "The completed result" in peer.turn.prompt
        assert "(ran 2 tools: read x2)" in peer.turn.prompt
        assert "hidden" not in peer.turn.prompt and "FOCUS_PRIVATE_" not in peer.turn.prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_incomplete_runs_discard_candidate_reply_but_keep_tool_counts(workspace, cancel):
    orch, store, factory, cid = workspace
    runner = await start(orch, factory, cid)
    runner.emit("tool_call", tool="bash", input={"command": "secret"})
    runner.emit("message", text="unfinished candidate")
    runner.emit("usage", tokens_in=1)
    await eventually(lambda: store.get_run(runner.turn.run.run_id).tokens_in == 1)
    if cancel:
        await orch.cancel_run(runner.turn.run.run_id)
    else:
        runner.emit("run_finished", ok=False, error="failed")
    await eventually(lambda: store.get_run(runner.turn.run.run_id).status in {"failed", "cancelled"})
    assert messages(store, cid) == []
    assert [e.payload["tools"] for e in store.events(cid) if e.kind == "tool_summary"] == [{"bash": 1}]
    assert runner.turn.run.run_id not in orch._pending_messages
    assert runner.turn.run.run_id not in orch._tool_counts


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,has_tool", [("commentary", False), (None, True)])
async def test_progress_is_not_mistaken_for_final_reply(workspace, phase, has_tool):
    orch, store, factory, cid = workspace
    runner = await start(orch, factory, cid)
    runner.emit("message", text="I will inspect the files", **({"phase": phase} if phase else {}))
    if has_tool:
        runner.emit("tool_call", tool="read", input={})
    await finish(store, runner, "")
    assert messages(store, cid) == []


@pytest.mark.asyncio
async def test_authoritative_terminal_reply_and_questions_are_saved_as_normal_messages(workspace):
    orch, store, factory, cid = workspace
    runner = await start(orch, factory, cid)
    runner.emit("message", text="discard this progress")
    runner.emit("run_finished", ok=True, final_message={"text": "Which branch should I use?"})
    await eventually(lambda: store.get_run(runner.turn.run.run_id).status == "completed")
    assert messages(store, cid) == ["Which branch should I use?"]
    followup = await start(orch, factory, cid, "Use main")
    assert "Which branch should I use?" in followup.turn.prompt and "Use main" in followup.turn.prompt
    assert "discard this progress" not in followup.turn.prompt


@pytest.mark.asyncio
async def test_quiet_artefact_delivers_and_opens_only_the_final_announcement(workspace):
    orch, store, factory, cid = workspace
    subscription = orch.bus.subscribe({cid}, 1000)
    runner = await start(orch, factory, cid)
    directory = artefacts.root(runner.turn.channel)
    (directory / "plan.md").write_text("# Completed plan")
    control = '```lgt-artefact\n{"name":"plan.md","path":"plan.md"}\n```'
    assert "omit intermediate announcements" in runner.turn.prompt
    runner.emit("message", text=control)
    runner.emit("tool_call", tool="read", input={})
    await finish(store, runner, control)
    saved = [e for e in store.events(cid) if e.kind == "message" and e.author_kind == "agent"]
    assert len(saved) == 1 and saved[0].payload["artefact"]["name"] == "plan.md"
    assert len([frame for frame in drain(subscription) if frame["type"] == "artefact_open"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["delegation", "handoff"])
async def test_only_final_reply_dispatches_transfers_with_visible_history(workspace, mode):
    orch, store, factory, cid = workspace
    runner = await start(orch, factory, cid)
    runner.emit("message", text="<@beta:delegation> hidden work", phase="commentary")
    runner.emit("usage", tokens_in=1)
    await eventually(lambda: store.get_run(runner.turn.run.run_id).tokens_in == 1)
    assert len(factory.started) == 1 and messages(store, cid) == []
    await finish(store, runner, f"<@beta:{mode}> Review the final result")
    await eventually(lambda: len(factory.started) == 2)
    peer = factory.started[1]
    assert peer.turn.agent.agent_id == "beta"
    assert "Review the final result" in peer.turn.prompt and "hidden work" not in peer.turn.prompt
    await eventually(lambda: store.get_channel(cid).primary_agent_id == ("beta" if mode == "handoff" else "alpha"))


@pytest.mark.asyncio
async def test_switching_applies_next_turn_and_never_recovers_hidden_history(workspace):
    orch, store, factory, cid = workspace
    quiet = await start(orch, factory, cid)
    quiet.emit("message", text="discarded quiet progress", phase="commentary")
    await orch.patch_channel(cid, focus_mode=True)
    assert quiet.turn.channel.focus_mode is False
    await finish(store, quiet, "quiet result")
    focused = await start(orch, factory, cid)
    assert focused.turn.channel.focus_mode is True and focused.turn.run.session_mode == "cold"
    assert "quiet result" in focused.turn.prompt and "discarded quiet progress" not in focused.turn.prompt
    subscription = orch.bus.subscribe({cid}, 1000)
    focused.emit("text_delta", text="live text")
    focused.emit("tool_call", tool="read", input={"path": "visible path"})
    focused.emit("tool_result", output="visible output")
    focused.emit("message", text="visible intermediate text")
    await eventually(lambda: "visible intermediate text" in messages(store, cid))
    assert any(f["type"] == "delta" for f in drain(subscription))
    assert any(e.kind == "tool_call" for e in store.events(cid))
    await orch.patch_channel(cid, focus_mode=False)
    focused.emit("message", text="still visible before next turn")
    await eventually(lambda: "still visible before next turn" in messages(store, cid))
    await finish(store, focused, "focused result")
    next_quiet = await start(orch, factory, cid)
    assert next_quiet.turn.channel.focus_mode is False and next_quiet.turn.run.session_mode == "cold"
    await finish(store, next_quiet)
    await orch.patch_channel(cid, focus_mode=True)
    new_focus = await start(orch, factory, cid)
    assert new_focus.turn.run.session_mode == "cold"
    await finish(store, new_focus)
    resumed_focus = await start(orch, factory, cid)
    assert resumed_focus.turn.run.session_mode == "resume"


@pytest.mark.asyncio
async def test_focus_sessions_are_invalidated_even_when_toggled_back_before_next_run(workspace):
    orch, store, factory, cid = workspace
    await orch.patch_channel(cid, focus_mode=True)
    runner = await start(orch, factory, cid)
    await finish(store, runner)
    assert orch.context_stats(cid, "alpha")["mode"] == "resume"
    await orch.patch_channel(cid, focus_mode=False)
    await orch.patch_channel(cid, focus_mode=True)
    assert orch.context_stats(cid, "alpha")["mode"] == "cold"


@pytest.mark.asyncio
async def test_channel_and_dm_preferences_are_independent_and_survive_reopen(workspace):
    orch, store, _, cid = workspace
    dm = store.get_agent("alpha").dm_channel_id
    assert not store.get_channel(cid).focus_mode and not store.get_channel(dm).focus_mode
    await orch.patch_channel(dm, focus_mode=True)
    assert not store.get_channel(cid).focus_mode and store.get_channel(dm).focus_mode
    path = store.conn.execute("PRAGMA database_list").fetchone()[2]
    reopened = Store(path)
    try:
        assert not reopened.get_channel(cid).focus_mode and reopened.get_channel(dm).focus_mode
    finally:
        reopened.close()
