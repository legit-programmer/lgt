from __future__ import annotations

import json

import pytest

from lgt.models import Agent, WorkspaceError
from lgt.orchestrator import Orchestrator
from lgt.store import Store
from lgt.transfers import parse_inline_transfers, parse_transfer
from tests.support import ControlledFactory, eventually, settings


@pytest.fixture
async def workspace(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    orch = Orchestrator(store, settings(tmp_path), factory, lambda *args: True, human_id="local")
    for name in ["coder", "assistant", "reviewer"]:
        orch.put_agent(Agent(name, name, name, name + " specialist", "codex", "", "help"))
    channel = orch.create_channel("test", agent_ids=["coder", "assistant", "reviewer"], primary_agent_id="coder")
    channel = store.patch_channel(channel.channel_id, focus_mode=True)
    await orch.start()
    yield orch, store, factory, channel.channel_id
    await orch.close()
    store.close()


def transfer(runner, mode, target, text="Schedule the requested meeting tomorrow"):
    runner.emit("message", text="```lgt-transfer\n" + json.dumps({
        "mode": mode, "target": target, "text": text,
    }) + "\n```")


def owner(store, cid):
    return store.get_channel(cid).primary_agent_id


@pytest.mark.asyncio
async def test_first_assignment_sticks_after_completion_and_is_shared_by_users(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Create a web page")
    await eventually(lambda: len(factory.started) == 1)
    assert owner(store, cid) == "coder"
    factory.started[0].finish("Created the page; tests passed")
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    store.add_member(cid, "human", "another-user")
    orch.human_id = "another-user"
    await orch.send_message(cid, "Good work. Now make the button red")
    await eventually(lambda: len(factory.started) == 2)
    assert factory.started[1].turn.agent.agent_id == "coder"
    assert store.channel_summary(cid, "local")["primary_agent_id"] == "coder"
    assert "assistant specialist" in factory.started[1].turn.prompt
    assert "allow_handoff" in factory.started[1].turn.prompt


@pytest.mark.asyncio
async def test_overlap_keeps_selected_primary_without_completion_stealing(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Code", ["coder"])
    await orch.send_message(cid, "Schedule", ["assistant"])
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "assistant"
    assert store.routing_state(cid)["routing_mode"] == "primary"
    message = await orch.send_message(cid, "Move it to noon")
    assert [(q.event_seq, q.agent_id) for q in store.queue(cid, "awaiting_agent")] == [(message.seq, "assistant")]
    assert not store.queue(cid, "awaiting_route")
    factory.started[0].finish("Code complete")
    factory.started[1].finish("Meeting scheduled")
    await eventually(lambda: len(factory.started) == 3)
    assert factory.started[2].turn.agent.agent_id == "assistant"
    factory.started[2].finish()
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    assert owner(store, cid) == "assistant"

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["handoff", "delegation", "mention"])
async def test_agent_task_result_pings_requester_without_changing_owner(workspace, mode):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Change the design")
    await eventually(lambda: len(factory.started) == 1)
    if mode == "mention":
        factory.started[0].emit("message", text="@assistant Change the design")
    else:
        transfer(factory.started[0], mode, "assistant", "Change the design")
    await eventually(lambda: len(factory.started) == 2)
    prompt = factory.started[1].turn.prompt
    assert "report back to that requesting agent" in prompt
    assert "assigned message's author_id, not the current primary" in prompt
    assert "do not ping back merely to acknowledge it" in prompt
    routing = prompt.split("<channel_routing>\n", 1)[1].split("\n</channel_routing>", 1)[0]
    assert json.loads(routing.split("\n", 1)[1])["assigned_messages"][0]["author_id"] == "coder"
    factory.started[0].finish()
    await eventually(lambda: store.get_run(factory.started[0].turn.run.run_id).status == "completed")
    expected_owner = "assistant" if mode == "handoff" else "coder"
    result = "<@coder:delegation> Design updated in page.html; layout checks passed."
    factory.started[1].finish(result)
    await eventually(lambda: len(factory.started) == 3)
    assert factory.started[2].turn.agent.agent_id == "coder"
    assert result in factory.started[2].turn.prompt
    assert owner(store, cid) == expected_owner
    factory.started[2].finish("The design change is complete.")
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    assert len(factory.started) == 3


@pytest.mark.asyncio
async def test_delegation_preserves_owner(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Create a site", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].emit("message", text="@reviewer review these changes")
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "coder"
    assert store.routing_state(cid) == {"routing_mode": "primary", "active_task_agent_ids": ["coder"]}
    await orch.send_message(cid, "Also make the button red")
    assert store.queue(cid, "awaiting_agent")[-1].agent_id == "coder"
    factory.started[1].finish("Review passed")
    factory.started[0].finish("Done")
    await eventually(lambda: len(factory.started) == 3)
    assert owner(store, cid) == "coder"


@pytest.mark.asyncio
async def test_accepted_handoff_transfers_ownership_and_allows_return_handoff(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Schedule a meeting", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "handoff", "assistant")
    await eventually(lambda: owner(store, cid) == "assistant")
    assert len(factory.started) == 2
    assert store.routing_state(cid) == {"routing_mode": "primary", "active_task_agent_ids": ["assistant"]}
    factory.started[0].finish("The assistant has the task")
    await eventually(lambda: store.get_run(factory.started[0].turn.run.run_id).status == "completed")
    assert owner(store, cid) == "assistant"
    transfer(factory.started[1], "handoff", "coder", "Change the button to red")
    await eventually(lambda: owner(store, cid) == "coder")
    assert len(factory.started) == 3
    reasons = [e.payload["reason"] for e in store.events(cid) if e.kind == "ownership_changed"]
    assert reasons == ["user_selection", "accepted_handoff", "accepted_handoff"]


@pytest.mark.asyncio
async def test_disabled_handoff_can_still_delegate(workspace):
    orch, store, factory, cid = workspace
    await orch.patch_channel(cid, allow_handoff=False)
    await orch.send_message(cid, "Work", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "handoff", "assistant")
    await eventually(lambda: any(e.kind == "agent_transfer" and e.payload["status"] == "rejected"
                                 for e in store.events(cid)))
    assert len(factory.started) == 1 and owner(store, cid) == "coder"
    transfer(factory.started[0], "delegation", "assistant")
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "coder"
    assert store.routing_state(cid)["routing_mode"] == "primary"


@pytest.mark.asyncio
async def test_delayed_handoff_cannot_override_newer_user_selection(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "A new task", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "delegation", "assistant", "An existing delegated calendar task")
    await eventually(lambda: len(factory.started) == 2)
    transfer(factory.started[0], "handoff", "assistant")
    await eventually(lambda: bool(store.queue(cid, "awaiting_agent")))
    await orch.send_message(cid, "Review something else", ["reviewer"])
    await eventually(lambda: len(factory.started) == 3)
    factory.started[1].finish()
    await eventually(lambda: len(factory.started) == 4)
    await eventually(lambda: any(e.kind == "agent_transfer" and e.payload["status"] == "rejected"
                                 for e in store.events(cid)))
    assert owner(store, cid) == "reviewer"


@pytest.mark.asyncio
async def test_overlap_allows_current_primary_handoff(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Calendar", ["assistant"])
    await orch.send_message(cid, "Code", ["coder"])
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "coder" and store.routing_state(cid)["routing_mode"] == "primary"
    transfer(factory.started[1], "handoff", "reviewer")
    await eventually(lambda: owner(store, cid) == "reviewer")
    assert len(factory.started) == 3

@pytest.mark.asyncio
async def test_handoff_is_not_coalesced_with_surrounding_delegation(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Work", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "delegation", "reviewer", "Initial review")
    await eventually(lambda: len(factory.started) == 2)
    transfer(factory.started[0], "delegation", "reviewer", "Another review")
    transfer(factory.started[0], "handoff", "reviewer", "Own the remaining review")
    transfer(factory.started[0], "delegation", "reviewer", "One additional check")
    await eventually(lambda: len(store.queue(cid, "awaiting_agent")) == 3)
    factory.started[1].finish()
    await eventually(lambda: len(factory.started) == 3)
    assert owner(store, cid) == "coder" and len(factory.started[2].turn.delivery_seqs) == 1
    factory.started[2].finish()
    await eventually(lambda: owner(store, cid) == "reviewer")
    assert len(factory.started) == 4 and len(factory.started[3].turn.delivery_seqs) == 1
    factory.started[3].finish()
    await eventually(lambda: len(factory.started) == 5)
    assert store.get_run(factory.started[4].turn.run.run_id).task_owner_id == "reviewer"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidate", ["disable", "remove_source"])
async def test_pending_handoff_rechecks_policy_and_source_membership(workspace, invalidate):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Task", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "delegation", "assistant", "Initial delegated work")
    await eventually(lambda: len(factory.started) == 2)
    transfer(factory.started[0], "handoff", "assistant")
    await eventually(lambda: bool(store.queue(cid, "awaiting_agent")))
    if invalidate == "disable":
        await orch.patch_channel(cid, allow_handoff=False)
    else:
        await orch.remove_member(cid, "coder")
    factory.started[1].finish()
    await eventually(lambda: len(factory.started) == 3)
    await eventually(lambda: any(e.kind == "agent_transfer" and e.payload["status"] == "rejected"
                                 for e in store.events(cid)))
    assert owner(store, cid) == "coder"


@pytest.mark.asyncio
async def test_cancel_before_receiver_starts_does_not_transfer_ownership(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Task", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    for _ in range(3):
        await orch._semaphore.acquire()
    transfer(factory.started[0], "handoff", "assistant")
    await eventually(lambda: len(store.list_runs(cid, active_only=True)) == 2)
    receiver = next(r for r in store.list_runs(cid, active_only=True) if r.agent_id == "assistant")
    await orch.cancel_run(receiver.run_id)
    assert owner(store, cid) == "coder" and len(factory.started) == 1
    for _ in range(3):
        orch._semaphore.release()


@pytest.mark.asyncio
async def test_explicit_primary_selection_controls_next_unmentioned_message(workspace):
    orch, store, factory, cid = workspace
    await orch.patch_channel(cid, primary_agent_id="assistant")
    await orch.send_message(cid, "Schedule a meeting")
    await eventually(lambda: len(factory.started) == 1)
    assert factory.started[0].turn.agent.agent_id == "assistant"
    assert owner(store, cid) == "assistant"

@pytest.mark.asyncio
async def test_independent_delivery_to_delegate_keeps_primary_and_stays_separate(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Code", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "delegation", "reviewer", "Review this code")
    await eventually(lambda: len(factory.started) == 2)
    await orch.send_message(cid, "Review an unrelated project", ["reviewer"])
    assert store.routing_state(cid)["routing_mode"] == "primary"
    factory.started[1].finish()
    await eventually(lambda: len(factory.started) == 3)
    run = store.get_run(factory.started[2].turn.run.run_id)
    assert run.task_owner_id == "reviewer"
    assert store.routing_state(cid)["routing_mode"] == "primary"


@pytest.mark.asyncio
async def test_removing_primary_requires_explicit_replacement(workspace):
    orch, store, factory, cid = workspace
    await orch.remove_member(cid, "coder")
    assert store.routing_state(cid)["routing_mode"] == "unassigned"
    before = len(store.events(cid))
    with pytest.raises(WorkspaceError):
        await orch.send_message(cid, "Schedule")
    assert len(store.events(cid)) == before
    await orch.patch_channel(cid, primary_agent_id="assistant")
    await orch.send_message(cid, "Schedule")
    await eventually(lambda: len(factory.started) == 1)
    assert factory.started[0].turn.agent.agent_id == "assistant"

@pytest.mark.asyncio
async def test_ownership_and_handoff_setting_survive_restart(workspace, tmp_path):
    orch, store, factory, cid = workspace
    await orch.patch_channel(cid, allow_handoff=False)
    await orch.send_message(cid, "Code", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].finish()
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    await orch.close()
    reopened = Store(tmp_path / "db.sqlite")
    second = Orchestrator(reopened, orch.settings, factory, lambda *args: True, human_id="local")
    try:
        await second.start()
        assert not reopened.get_channel(cid).allow_handoff
        assert owner(reopened, cid) == "coder"
        await second.send_message(cid, "Make it red")
        await eventually(lambda: len(factory.started) == 2)
    finally:
        await second.close()
        reopened.close()


def test_transfer_controls_require_a_complete_valid_message():
    control = '```lgt-transfer\n{"mode":"handoff","target":"assistant","text":"Schedule"}\n```'
    assert parse_transfer(control)["mode"] == "handoff"
    assert parse_transfer("Example:\n" + control) is None
    assert parse_transfer("Ordinary completion") is None
    with pytest.raises(WorkspaceError):
        parse_transfer("```lgt-transfer\n{}\n```")
    with pytest.raises(WorkspaceError):
        parse_transfer("", {"mode": "handoff", "target": 123, "text": "Schedule"})
    with pytest.raises(WorkspaceError):
        parse_transfer("", {"mode": [], "target": "assistant", "text": "Schedule"})


@pytest.mark.asyncio
async def test_nonprimary_cannot_transfer_ownership(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Code", ["coder"])
    await orch.send_message(cid, "Calendar", ["assistant"])
    await eventually(lambda: len(factory.started) == 2)
    transfer(factory.started[0], "handoff", "reviewer")
    await eventually(lambda: any(e.kind == "agent_transfer" and e.payload["status"] == "rejected"
                                 for e in store.events(cid)))
    assert owner(store, cid) == "assistant" and len(factory.started) == 2


@pytest.mark.asyncio
async def test_multiple_mentions_select_last_recipient_for_followups(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Both work", ["coder", "assistant"])
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "assistant"
    await orch.send_message(cid, "Review the work")
    assert store.queue(cid, "awaiting_agent")[0].agent_id == "assistant"
    assert store.routing_state(cid)["routing_mode"] == "primary"
    for runner in factory.started[:2]:
        runner.finish()
    await eventually(lambda: len(factory.started) == 3)
    assert factory.started[2].turn.agent.agent_id == "assistant"
    factory.started[2].finish()
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    assert owner(store, cid) == "assistant"

@pytest.mark.parametrize("text", [
    "`<@reviewer:delegation>`",
    "`` <@reviewer:delegation> ` example ``",
    "```python\n<@reviewer:delegation>\n```",
    "~~~\n<@reviewer:handoff>\n~~~",
    "```\n<@reviewer:handoff>",
    "    <@reviewer:delegation>",
    "\t<@reviewer:delegation>",
    "> ```\n> <@reviewer:delegation>\n> ```",
    "> <@reviewer:delegation>",
    r"\<@reviewer:delegation>",
])
def test_inline_transfer_examples_do_not_execute(text):
    assert parse_inline_transfers(text) == []


def test_inline_transfers_allow_prose_and_reject_multiple_handoffs():
    text = "Ready. <@assistant:handoff> Schedule it. <@reviewer:delegation> Review."
    assert [(t["target"], t["mode"]) for t in parse_inline_transfers(text)] == [
        ("assistant", "handoff"), ("reviewer", "delegation")]
    assert all(t["text"] == text for t in parse_inline_transfers(text))
    with pytest.raises(WorkspaceError, match="at most one handoff"):
        parse_inline_transfers("<@assistant:handoff> <@reviewer:handoff>")


@pytest.mark.asyncio
async def test_inline_transfers_dispatch_only_complete_message_with_full_context(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Implement", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    text = "I read the requirements. <@assistant:delegation> Check scheduling. <@reviewer:delegation> Review code."
    factory.started[0].emit("text_delta", text=text)
    await eventually(lambda: orch._partials.get(factory.started[0].turn.run.run_id) == text)
    assert len(factory.started) == 1
    assert not store.queue(cid, "awaiting_agent")
    factory.started[0].emit("message", text=text)
    await eventually(lambda: len(factory.started) == 3)
    message = next(e for e in store.events(cid) if e.kind == "message" and e.author_kind == "agent")
    assert message.payload["text"] == text
    assert message.payload["mentions"] == ["assistant", "reviewer"]
    assert len(message.payload["transfers"]) == 2
    assert "transfer" not in message.payload
    for runner in factory.started[1:]:
        routing = runner.turn.prompt.split("<channel_routing>\n", 1)[1].split("\n</channel_routing>", 1)[0]
        assigned = json.loads(routing[routing.index("{\"primary_agent_id\""):])["assigned_messages"]
        assert assigned[0]["text"] == text
        assert assigned[0]["transfers"] == message.payload["transfers"]
    assert owner(store, cid) == "coder"


@pytest.mark.asyncio
async def test_mixed_inline_handoff_and_delegation_accept_only_handoff_recipient(workspace, monkeypatch):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Implement", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    frames = []
    publish = orch.bus.publish
    def record(frame):
        frames.append(frame)
        publish(frame)
    monkeypatch.setattr(orch.bus, "publish", record)
    factory.started[0].emit("message", text="<@reviewer:delegation> Review. <@assistant:handoff> Own this.")
    await eventually(lambda: len(factory.started) == 3 and owner(store, cid) == "assistant")
    accepted = [e for e in store.events(cid) if e.kind == "agent_transfer" and e.payload["status"] == "accepted"]
    assert len(accepted) == 1 and accepted[0].payload["targets"] == ["assistant"]
    seqs = [frame["event"]["seq"] for frame in frames if frame["type"] == "event"]
    assert seqs == sorted(seqs)


@pytest.mark.asyncio
async def test_rejected_inline_handoff_still_dispatches_delegation(workspace):
    orch, store, factory, cid = workspace
    await orch.patch_channel(cid, allow_handoff=False)
    await orch.send_message(cid, "Implement", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].emit("message", text="<@assistant:handoff> Own this. <@reviewer:delegation> Review.")
    await eventually(lambda: len(factory.started) == 2)
    assert factory.started[1].turn.agent.agent_id == "reviewer"
    assert owner(store, cid) == "coder"
    assert any(e.kind == "agent_transfer" and e.payload["status"] == "rejected" for e in store.events(cid))


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["<@outside:delegation> Check", "<@coder:delegation> Check", "<@assistant:handoff> <@reviewer:handoff>"])
async def test_invalid_inline_transfers_fail_without_partial_dispatch(workspace, text):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Implement", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].emit("message", text=text)
    await eventually(lambda: store.get_run(factory.started[0].turn.run.run_id).status == "failed")
    assert len(factory.started) == 1
    assert not store.queue(cid, "awaiting_agent")
    assert owner(store, cid) == "coder"


@pytest.mark.asyncio
async def test_code_examples_and_cancelled_stream_do_not_dispatch(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "Implement", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].emit("message", text="Example: `<@reviewer:delegation>` and `@assistant`\n```\n<@assistant:handoff>\n```")
    await eventually(lambda: any(e.kind == "message" and e.author_kind == "agent" for e in store.events(cid)))
    assert len(factory.started) == 1
    factory.started[0].emit("text_delta", text="<@assistant:handoff> Take over")
    await eventually(lambda: bool(orch._partials))
    await orch.cancel_run(factory.started[0].turn.run.run_id)
    assert len(factory.started) == 1 and owner(store, cid) == "coder"


@pytest.mark.asyncio
async def test_human_typed_transfer_is_not_an_ownership_request(workspace):
    orch, store, factory, cid = workspace
    await orch.send_message(cid, "<@assistant:handoff> Example", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    assert factory.started[0].turn.agent.agent_id == "coder"
    assert owner(store, cid) == "coder"
    assert not any(e.kind == "agent_transfer" for e in store.events(cid))
