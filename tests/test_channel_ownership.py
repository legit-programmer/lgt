from __future__ import annotations

import asyncio
import json

import pytest

from lgt.models import Agent, RoutingDecision, WorkspaceError
from lgt.orchestrator import Orchestrator
from lgt.store import Store
from lgt.transfers import parse_transfer
from tests.support import ControlledFactory, FakeRouter, eventually, settings


@pytest.fixture
async def workspace(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    router = FakeRouter(["coder"])
    orch = Orchestrator(store, settings(tmp_path), router, factory, lambda *args: True, human_id="local")
    for name in ["coder", "assistant", "reviewer"]:
        orch.put_agent(Agent(name, name, name, name + " specialist", "codex", "", "help"))
    channel = orch.create_channel("test", agent_ids=["coder", "assistant", "reviewer"])
    await orch.start()
    yield orch, store, factory, router, channel.channel_id
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
    orch, store, factory, router, cid = workspace
    await orch.send_message(cid, "Create a web page")
    await eventually(lambda: len(factory.started) == 1)
    assert len(router.calls) == 1 and owner(store, cid) == "coder"
    factory.started[0].finish("Created the page; tests passed")
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    store.add_member(cid, "human", "another-user")
    orch.human_id = "another-user"
    await orch.send_message(cid, "Good work. Now make the button red")
    await eventually(lambda: len(factory.started) == 2)
    assert factory.started[1].turn.agent.agent_id == "coder"
    assert len(router.calls) == 1
    assert store.channel_summary(cid, "local")["primary_agent_id"] == "coder"
    assert "assistant specialist" in factory.started[1].turn.prompt
    assert "allow_handoff" in factory.started[1].turn.prompt


@pytest.mark.asyncio
async def test_overlap_uses_router_and_restores_selected_owner_without_completion_stealing(workspace):
    orch, store, factory, router, cid = workspace
    await orch.send_message(cid, "Code", ["coder"])
    await orch.send_message(cid, "Schedule", ["assistant"])
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "assistant" and not router.calls
    assert store.routing_state(cid)["routing_mode"] == "router"
    router.picks = ["assistant"]
    await orch.send_message(cid, "Move it to noon")
    await eventually(lambda: len(router.calls) == 1 and bool(store.queue(cid, "awaiting_agent")))
    assert all(r["busy"] for r in router.calls[0].roster if r["agent_id"] != "reviewer")
    factory.started[0].finish("Code complete")
    await eventually(lambda: store.routing_state(cid)["routing_mode"] == "primary")
    assert owner(store, cid) == "assistant"
    factory.started[1].finish("Meeting scheduled")
    await eventually(lambda: len(factory.started) == 3)
    factory.started[2].finish()
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    assert owner(store, cid) == "assistant"


@pytest.mark.asyncio
async def test_delegation_preserves_owner_and_does_not_enable_router(workspace):
    orch, store, factory, router, cid = workspace
    await orch.send_message(cid, "Create a site", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].emit("message", text="@reviewer review these changes")
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "coder"
    assert store.routing_state(cid) == {"routing_mode": "primary", "active_task_agent_ids": ["coder"]}
    await orch.send_message(cid, "Also make the button red")
    assert not router.calls
    assert store.queue(cid, "awaiting_agent")[-1].agent_id == "coder"
    factory.started[1].finish("Review passed")
    factory.started[0].finish("Done")
    await eventually(lambda: len(factory.started) == 3)
    assert owner(store, cid) == "coder"


@pytest.mark.asyncio
async def test_accepted_handoff_transfers_ownership_and_allows_return_handoff(workspace):
    orch, store, factory, router, cid = workspace
    await orch.send_message(cid, "Schedule a meeting", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "handoff", "assistant")
    await eventually(lambda: owner(store, cid) == "assistant")
    assert len(factory.started) == 2 and not router.calls
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
    orch, store, factory, router, cid = workspace
    await orch.patch_channel(cid, allow_handoff=False)
    await orch.send_message(cid, "Work", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "handoff", "assistant")
    await eventually(lambda: any(e.kind == "agent_transfer" and e.payload["status"] == "rejected"
                                 for e in store.events(cid)))
    assert len(factory.started) == 1 and owner(store, cid) == "coder"
    transfer(factory.started[0], "delegation", "assistant")
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "coder" and not router.calls
    assert store.routing_state(cid)["routing_mode"] == "primary"


@pytest.mark.asyncio
async def test_delayed_handoff_cannot_override_newer_user_selection(workspace):
    orch, store, factory, _, cid = workspace
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
async def test_router_mode_prevents_specialist_handoff(workspace):
    orch, store, factory, _, cid = workspace
    await orch.send_message(cid, "Calendar", ["assistant"])
    await orch.send_message(cid, "Code", ["coder"])
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "coder" and store.routing_state(cid)["routing_mode"] == "router"
    transfer(factory.started[1], "handoff", "reviewer")
    await eventually(lambda: any(e.kind == "agent_transfer" and e.payload["status"] == "rejected"
                                 for e in store.events(cid)))
    assert owner(store, cid) == "coder" and len(factory.started) == 2


@pytest.mark.asyncio
async def test_handoff_is_not_coalesced_with_surrounding_delegation(workspace):
    orch, store, factory, _, cid = workspace
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
    orch, store, factory, _, cid = workspace
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
    orch, store, factory, _, cid = workspace
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
async def test_stale_router_result_cannot_override_explicit_selection(workspace):
    orch, store, factory, router, cid = workspace
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed_route(request):
        entered.set()
        await release.wait()
        return RoutingDecision(["coder"], "Initial assignment")
    router.route = delayed_route
    await orch.send_message(cid, "Create a site")
    await entered.wait()
    await orch.send_message(cid, "Schedule a meeting", ["assistant"])
    release.set()
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "assistant"
    assert [e.payload["reason"] for e in store.events(cid) if e.kind == "ownership_changed"] == ["user_selection"]


@pytest.mark.asyncio
async def test_independent_delivery_to_delegate_enables_router_and_stays_separate(workspace):
    orch, store, factory, _, cid = workspace
    await orch.send_message(cid, "Code", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    transfer(factory.started[0], "delegation", "reviewer", "Review this code")
    await eventually(lambda: len(factory.started) == 2)
    await orch.send_message(cid, "Review an unrelated project", ["reviewer"])
    assert store.routing_state(cid)["routing_mode"] == "router"
    factory.started[1].finish()
    await eventually(lambda: len(factory.started) == 3)
    run = store.get_run(factory.started[2].turn.run.run_id)
    assert run.task_owner_id == "reviewer"
    assert store.routing_state(cid)["routing_mode"] == "router"


@pytest.mark.asyncio
async def test_removing_primary_falls_back_to_router(workspace):
    orch, store, factory, router, cid = workspace
    await orch.send_message(cid, "Code", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    await orch.remove_member(cid, "coder")
    router.picks = ["assistant"]
    await orch.send_message(cid, "Schedule")
    await eventually(lambda: owner(store, cid) == "assistant")
    assert len(router.calls) == 1


@pytest.mark.asyncio
async def test_ownership_and_handoff_setting_survive_restart(workspace, tmp_path):
    orch, store, factory, router, cid = workspace
    await orch.patch_channel(cid, allow_handoff=False)
    await orch.send_message(cid, "Code", ["coder"])
    await eventually(lambda: len(factory.started) == 1)
    factory.started[0].finish()
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    await orch.close()
    reopened = Store(tmp_path / "db.sqlite")
    second = Orchestrator(reopened, orch.settings, router, factory, lambda *args: True, human_id="local")
    try:
        await second.start()
        assert not reopened.get_channel(cid).allow_handoff
        assert owner(reopened, cid) == "coder"
        await second.send_message(cid, "Make it red")
        await eventually(lambda: len(factory.started) == 2)
        assert not router.calls
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
    orch, store, factory, _, cid = workspace
    await orch.send_message(cid, "Code", ["coder"])
    await orch.send_message(cid, "Calendar", ["assistant"])
    await eventually(lambda: len(factory.started) == 2)
    transfer(factory.started[0], "handoff", "reviewer")
    await eventually(lambda: any(e.kind == "agent_transfer" and e.payload["status"] == "rejected"
                                 for e in store.events(cid)))
    assert owner(store, cid) == "assistant" and len(factory.started) == 2


@pytest.mark.asyncio
async def test_multiple_mentions_and_router_assignments_have_deterministic_owners(workspace):
    orch, store, factory, router, cid = workspace
    await orch.send_message(cid, "Both work", ["coder", "assistant"])
    await eventually(lambda: len(factory.started) == 2)
    assert owner(store, cid) == "assistant"
    router.picks = ["reviewer", "coder"]
    await orch.send_message(cid, "Review the work")
    await eventually(lambda: owner(store, cid) == "reviewer")
    assert store.routing_state(cid)["routing_mode"] == "router"
    for runner in factory.started[:2]:
        runner.finish()
    await eventually(lambda: len(factory.started) == 4)
    factory.started[2].finish()
    factory.started[3].finish()
    await eventually(lambda: not store.list_runs(cid, active_only=True))
    assert owner(store, cid) == "reviewer" and store.routing_state(cid)["routing_mode"] == "primary"
