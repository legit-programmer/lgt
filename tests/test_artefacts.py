from dataclasses import replace
import json

import pytest

from lgt import artefacts
from lgt.models import Channel, WorkspaceError
from tests.test_orchestrator import workspace
from tests.support import eventually


@pytest.fixture
def channel(tmp_path):
    return Channel("channel-a", "channel", "test", str(tmp_path), False)


def test_folder_is_source_of_truth_and_isolated(channel):
    directory = artefacts.root(channel, setup=True)
    (directory / "plan.md").write_text("# Plan")
    (directory / "ignored.txt").write_text("not supported")
    assert [f["name"] for f in artefacts.listing(channel)] == ["plan.md"]
    assert artefacts.listing(replace(channel, channel_id="channel-b")) == []
    (directory / "plan.md").rename(directory / "renamed.md")
    assert artefacts.listing(channel)[0]["name"] == "renamed.md"
    (directory / "renamed.md").rename(directory.parent / "moved.md")
    assert artefacts.listing(channel) == []
    (directory / "plan.md").write_text("# Plan")
    assert artefacts.listing(replace(channel, cwd=str(directory / "elsewhere"))) == []
    directory.rename(directory.with_name("renamed-channel"))
    assert artefacts.listing(channel) == []


def test_paths_and_symlinks_cannot_escape(channel, tmp_path):
    directory = artefacts.root(channel, setup=True)
    outside = tmp_path / "private.md"
    outside.write_text("secret")
    (directory / "link.md").symlink_to(outside)
    for name in ("../private.md", str(outside), "link.md", "a\\b.md", "a:stream.md"):
        with pytest.raises(WorkspaceError):
            artefacts.path_for(channel, name)
    assert artefacts.listing(channel) == []
    (directory / "link.md").unlink()
    directory.rmdir()
    directory.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(WorkspaceError):
        artefacts.root(channel, setup=True)


def test_announcement_only_accepts_complete_control_message(channel):
    directory = artefacts.root(channel, setup=True)
    (directory / "plan.md").write_text("# Plan")
    control = '```lgt-artefact\n{"name":"plan.md","path":"plan.md"}\n```'
    assert artefacts.announced_file(channel, artefacts.announcement(control))["kind"] == "markdown"
    for example in ("Example:\n" + control, "````markdown\n" + control + "\n````", "> " + control):
        assert artefacts.announcement(example) is None
    with pytest.raises(WorkspaceError):
        artefacts.announcement('```lgt-artefact\n{}\n```')
    with pytest.raises(WorkspaceError):
        artefacts.announced_file(channel, {"name": "plan.md", "path": str(directory.parent / "plan.md")})


@pytest.mark.asyncio
async def test_setup_announcement_update_and_mutations(workspace):
    orch, store, factory, channel = workspace
    await orch.send_message(channel.channel_id, "Make a plan")
    await eventually(lambda: len(factory.started) == 1)
    runner = factory.started[0]
    directory = artefacts.root(channel)
    assert directory.is_dir() and str(directory) in runner.turn.prompt
    path = directory / "plan.md"
    path.write_text("# One")
    control = '```lgt-artefact\n' + json.dumps({"name": path.name, "path": str(path)}) + '\n```'
    runner.emit("text_delta", text=control)
    await eventually(lambda: bool(orch._partials))
    assert not any(e.payload.get("artefact") for e in store.events(channel.channel_id))
    runner.emit("message", text=control)
    await eventually(lambda: any(e.payload.get("artefact") for e in store.events(channel.channel_id)))
    path.write_text("# Updated")
    runner.finish(control)
    await eventually(lambda: len([e for e in store.events(channel.channel_id) if e.payload.get("artefact")]) == 2)
    await orch.mutate_artefact(channel.channel_id, "plan.md", "renamed.md")
    assert not path.exists() and (directory / "renamed.md").is_file()
    (directory / "exists.md").write_text("exists")
    with pytest.raises(WorkspaceError):
        await orch.mutate_artefact(channel.channel_id, "renamed.md", "exists.md")
    await orch.mutate_artefact(channel.channel_id, "renamed.md", None)
    assert not (directory / "renamed.md").exists()
    assert store.events(channel.channel_id)[-1].kind == "artefact_changed"


@pytest.mark.asyncio
async def test_api_preview_capability_and_filesystem_changes(workspace):
    from types import SimpleNamespace
    import httpx
    from lgt.gateway import create_app

    orch, _, _, channel = workspace
    directory = artefacts.root(channel, setup=True)
    (directory / "visual.html").write_text("<script>document.body.textContent='OK'</script>")
    prefix = f"/channels/{channel.channel_id}/artefacts"
    app = create_app(orch, manage_lifespan=False, daemon=SimpleNamespace(token="test-token"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get(prefix)).status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        assert (await client.get(prefix)).json()[0]["name"] == "visual.html"
        raw = await client.get(prefix + "/content", params={"path": "visual.html"})
        assert raw.headers["content-type"].startswith("text/plain")
        assert (await client.get(prefix + "/content", params={"path": "../secret.md"})).status_code == 400
        ticket = (await client.post(prefix + "/preview", params={"path": "visual.html"})).json()["url"]
        client.headers.clear()
        preview = await client.get(ticket, headers={"Origin": "null"})
        assert preview.status_code == 200
        assert "sandbox allow-scripts" in preview.headers["content-security-policy"]
        assert "allow-same-origin" not in preview.headers["content-security-policy"]
        assert (await client.get(ticket)).status_code == 404
        assert (await client.get(prefix, headers={"Origin": "null"})).status_code == 403
        client.headers["Authorization"] = "Bearer test-token"
        assert (await client.patch(prefix, params={"path": "visual.html"}, json={"name": "new.html"})).status_code == 204
        assert (await client.get(prefix)).json()[0]["name"] == "new.html"
        assert (await client.delete(prefix, params={"path": "new.html"})).status_code == 204
        assert (await client.get(prefix)).json() == []
