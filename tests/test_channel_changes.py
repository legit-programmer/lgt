from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lgt.attachments import AttachmentTooLarge, safe_filename
from lgt.codex_adapter import _turn_input
from lgt.models import Agent, RoutingDecision, WorkspaceError
from lgt.orchestrator import Orchestrator
from lgt.store import Store
from tests.support import ControlledFactory, FakeRouter, eventually, settings


@pytest.fixture
async def workspace(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    router = FakeRouter(["alpha"])
    orch = Orchestrator(store, settings(tmp_path / "data"), router, factory,
                        lambda harness, sid, cwd: True, human_id="local")
    for name in ["alpha", "beta"]:
        orch.put_agent(Agent(name, name, name, name + " specialist", "codex", "", "help"))
    channel = orch.create_channel("test", agent_ids=["alpha", "beta"])
    await orch.start()
    yield orch, store, factory, router, channel
    await orch.close()
    store.close()


def kinds(store, channel_id):
    return [event.kind for event in store.events(channel_id)]


async def chunks(*parts: bytes):
    for part in parts:
        yield part


# Working directory


@pytest.mark.asyncio
async def test_cwd_change_waits_for_idle_channel_and_forces_cold_rebuild(workspace, tmp_path):
    orch, store, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "first", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    target = tmp_path / "elsewhere"
    target.mkdir()
    with pytest.raises(WorkspaceError, match="active runs"):
        await orch.set_channel_cwd(channel.channel_id, str(target))
    factory.started[0].finish()
    await eventually(lambda: store.get_session("alpha", channel.channel_id) is not None)

    moved = await orch.set_channel_cwd(channel.channel_id, str(target))
    assert (moved.cwd, moved.cwd_managed) == (str(target), False)
    change = store.events(channel.channel_id)[-1]
    assert change.kind == "cwd_changed"
    assert change.payload == {"cwd": str(target), "previous_cwd": channel.cwd, "managed": False}

    await orch.send_message(channel.channel_id, "second", ["alpha"])
    await eventually(lambda: len(factory.started) == 2)
    turn = factory.started[1].turn
    assert turn.channel.cwd == str(target)
    assert turn.run.session_mode == "cold"
    assert f"The channel working directory is now {target}" in turn.prompt


@pytest.mark.asyncio
async def test_cwd_change_validates_paths_and_returns_to_managed_directory(workspace, tmp_path):
    orch, store, _, _, channel = workspace
    with pytest.raises(WorkspaceError, match="absolute"):
        await orch.set_channel_cwd(channel.channel_id, "relative/path")
    with pytest.raises(WorkspaceError, match="existing directory"):
        await orch.set_channel_cwd(channel.channel_id, str(tmp_path / "missing"))
    # Re-selecting the current managed directory is a no-op without an event.
    unchanged = await orch.set_channel_cwd(channel.channel_id, None)
    assert unchanged.cwd == channel.cwd and "cwd_changed" not in kinds(store, channel.channel_id)

    await orch.set_channel_cwd(channel.channel_id, str(tmp_path))
    back = await orch.set_channel_cwd(channel.channel_id, None)
    assert back.cwd == str(orch.settings.workspace_dir / channel.channel_id) and back.cwd_managed
    assert kinds(store, channel.channel_id).count("cwd_changed") == 2


# Members


@pytest.mark.asyncio
async def test_remove_member_cancels_its_run_and_pending_deliveries(workspace):
    orch, store, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    queued = await orch.send_message(channel.channel_id, "more", ["alpha"])
    assert orch.queue_items(channel.channel_id)[0]["event_seq"] == queued.seq

    event = await orch.remove_member(channel.channel_id, "alpha")
    assert event.kind == "member_removed"
    assert event.payload == {"agent_id": "alpha", "handle": "alpha", "cancelled_seqs": [queued.seq]}
    assert factory.started[0].cancelled
    assert store.list_runs(channel.channel_id)[0].status == "cancelled"
    assert orch.queue_items(channel.channel_id) == []
    assert [m["member_id"] for m in store.members(channel.channel_id) if m["member_kind"] == "agent"] == ["beta"]
    await asyncio.sleep(0.05)
    assert len(factory.started) == 1
    with pytest.raises(WorkspaceError, match="not a channel member"):
        await orch.send_message(channel.channel_id, "hi", ["alpha"])
    with pytest.raises(KeyError):
        await orch.remove_member(channel.channel_id, "alpha")


@pytest.mark.asyncio
async def test_member_events_render_and_re_adding_is_recorded_once(workspace):
    orch, store, factory, _, channel = workspace
    await orch.remove_member(channel.channel_id, "alpha")
    orch.add_member(channel.channel_id, "alpha")
    orch.add_member(channel.channel_id, "alpha")
    assert kinds(store, channel.channel_id) == ["member_removed", "member_added"]
    await orch.send_message(channel.channel_id, "go", ["beta"])
    await eventually(lambda: len(factory.started) == 1)
    prompt = factory.started[0].turn.prompt
    assert "[system] alpha left the channel" in prompt and "[system] alpha joined the channel" in prompt


@pytest.mark.asyncio
async def test_dm_agent_cannot_be_removed(workspace):
    orch, _, _, _, _ = workspace
    dm = orch.create_channel("alpha", "dm", ["alpha"])
    with pytest.raises(WorkspaceError, match="archive the DM"):
        await orch.remove_member(dm.channel_id, "alpha")


@pytest.mark.asyncio
async def test_routing_result_drops_an_agent_removed_while_routing(workspace):
    orch, store, factory, router, channel = workspace
    gate = asyncio.Event()

    async def slow_route(request):
        await gate.wait()
        return RoutingDecision(["alpha"], "fixture")

    router.route = slow_route
    await orch.send_message(channel.channel_id, "who takes this")
    await orch.remove_member(channel.channel_id, "alpha")
    gate.set()
    await eventually(lambda: "routing_decision" in kinds(store, channel.channel_id))
    decision = store.events(channel.channel_id)[-1]
    assert decision.payload["agents"] == []
    await asyncio.sleep(0.05)
    assert factory.started == []


# Queued deliveries


@pytest.mark.asyncio
async def test_cancelling_a_queued_message_retracts_it(workspace):
    orch, store, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    queued = await orch.send_message(channel.channel_id, "never mind this", ["alpha"])

    event = await orch.cancel_delivery(channel.channel_id, queued.seq)
    assert event.kind == "delivery_cancelled"
    assert event.payload == {"target_seq": queued.seq, "agent_ids": ["alpha"], "retracted": True}
    edit = store.events(channel.channel_id)[-1]
    assert edit.kind == "message_edit" and edit.payload == {"target_seq": queued.seq, "deleted": True}
    assert orch.queue_items(channel.channel_id) == []

    factory.started[0].finish()
    await orch.send_message(channel.channel_id, "next", ["alpha"])
    await eventually(lambda: len(factory.started) == 2)
    assert "never mind this" not in factory.started[1].turn.prompt
    with pytest.raises(WorkspaceError, match="no pending deliveries"):
        await orch.cancel_delivery(channel.channel_id, queued.seq)


@pytest.mark.asyncio
async def test_cancelling_one_recipient_keeps_a_delivered_message(workspace):
    orch, store, factory, _, channel = workspace
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    both = await orch.send_message(channel.channel_id, "@alpha @beta look at this")
    await eventually(lambda: len(factory.started) == 2)

    event = await orch.cancel_delivery(channel.channel_id, both.seq, ["@alpha"])
    assert event.payload == {"target_seq": both.seq, "agent_ids": ["alpha"], "retracted": False}
    assert store.events(channel.channel_id)[-1].kind == "delivery_cancelled"
    with pytest.raises(WorkspaceError, match="no pending deliveries"):
        await orch.cancel_delivery(channel.channel_id, both.seq, ["beta"])


@pytest.mark.asyncio
async def test_cancelling_during_routing_discards_the_routing_result(workspace):
    orch, store, factory, router, channel = workspace
    gate = asyncio.Event()

    async def slow_route(request):
        await gate.wait()
        return RoutingDecision(["alpha"], "fixture")

    router.route = slow_route
    message = await orch.send_message(channel.channel_id, "route me")
    assert orch.queue_items(channel.channel_id)[0]["state"] == "awaiting_route"
    event = await orch.cancel_delivery(channel.channel_id, message.seq)
    assert event.payload["agent_ids"] == [None] and event.payload["retracted"]
    gate.set()
    await asyncio.sleep(0.05)
    assert "routing_decision" not in kinds(store, channel.channel_id)
    assert factory.started == []


@pytest.mark.asyncio
async def test_queue_frames_follow_pending_deliveries(workspace):
    orch, _, factory, _, channel = workspace
    subscription = orch.bus.subscribe({channel.channel_id}, capacity=100)
    await orch.send_message(channel.channel_id, "work", ["alpha"])
    await eventually(lambda: len(factory.started) == 1)
    queued = await orch.send_message(channel.channel_id, "later", ["alpha"])
    factory.started[0].finish()
    await eventually(lambda: len(factory.started) == 2)
    frames = []
    while not subscription.queue.empty():
        frame = subscription.queue.get_nowait()
        if frame["type"] == "queue":
            frames.append(frame["items"])
    assert [[(i["event_seq"], i["agent_id"]) for i in items] for items in frames] == [
        [(queued.seq, "alpha")], [],
    ]
    assert orch.queue_snapshots({channel.channel_id}) == []


# Attachments


@pytest.mark.asyncio
async def test_attachment_is_bound_once_and_reaches_the_triggered_turn(workspace):
    orch, store, factory, _, channel = workspace
    image = await orch.create_attachment(channel.channel_id, "../shot.png", "image/png; q=1", chunks(b"\x89PNG", b"data"))
    notes = await orch.create_attachment(channel.channel_id, "notes.txt", None, chunks(b"hello"))
    assert (image.filename, image.media_type, image.size_bytes) == ("shot.png", "image/png", 8)
    assert notes.media_type == "application/octet-stream"
    assert Path(image.path).read_bytes() == b"\x89PNGdata"
    assert Path(image.path).parent.parent == orch.settings.attachment_dir

    message = await orch.send_message(channel.channel_id, "", ["alpha"], [image.attachment_id, notes.attachment_id])
    assert message.payload["attachments"] == [image.summary(), notes.summary()]
    assert store.get_attachment(image.attachment_id).message_seq == message.seq
    await eventually(lambda: len(factory.started) == 1)
    turn = factory.started[0].turn
    assert [a.attachment_id for a in turn.attachments] == [image.attachment_id, notes.attachment_id]
    assert f"(attached shot.png, image/png, 8 bytes, at {image.path})" in turn.prompt
    codex_input = _turn_input(turn)
    assert [type(item).__name__ for item in codex_input] == ["TextInput", "LocalImageInput"]
    assert codex_input[1].path == image.path

    with pytest.raises(WorkspaceError, match="already sent"):
        await orch.send_message(channel.channel_id, "again", ["alpha"], [image.attachment_id])
    with pytest.raises(WorkspaceError, match="cannot be deleted"):
        orch.delete_attachment(image.attachment_id)


@pytest.mark.asyncio
async def test_attachment_limits_ownership_and_unsent_deletion(workspace):
    orch, store, _, _, channel = workspace
    limit = orch.settings.attachment_max_bytes
    with pytest.raises(AttachmentTooLarge):
        await orch.create_attachment(channel.channel_id, "big.bin", None, chunks(b"x" * limit, b"y"))
    assert not orch.settings.attachment_dir.exists() or not any(orch.settings.attachment_dir.iterdir())

    other = orch.create_channel("other", agent_ids=["beta"])
    foreign = await orch.create_attachment(other.channel_id, "a.txt", "text/plain", chunks(b"a"))
    with pytest.raises(WorkspaceError, match="another channel"):
        await orch.send_message(channel.channel_id, "x", ["alpha"], [foreign.attachment_id])
    with pytest.raises(WorkspaceError, match="only once"):
        await orch.send_message(other.channel_id, "x", None, [foreign.attachment_id, foreign.attachment_id])
    with pytest.raises(WorkspaceError, match="text or an attachment"):
        await orch.send_message(channel.channel_id, "  ")

    orch.delete_attachment(foreign.attachment_id)
    assert not Path(foreign.path).exists()
    with pytest.raises(KeyError):
        store.get_attachment(foreign.attachment_id)


def test_safe_filename_strips_paths_and_reserved_names():
    assert safe_filename("C:\\Users\\me\\report.pdf") == "report.pdf"
    assert safe_filename("a<b>:c?.txt") == "a_b__c_.txt"
    assert safe_filename("CON.txt") == "file_CON.txt"
    assert safe_filename("..") == "file"
    long = safe_filename("n" * 300 + ".tar")
    assert len(long) == 200 and long.endswith(".tar")
