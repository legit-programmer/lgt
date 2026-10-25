from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lgt.gateway import create_app
from lgt.models import Agent
from lgt.orchestrator import Orchestrator
from tests.support import ControlledFactory, settings
from tests.test_gateway import ThreadSafeStore, _with_peer


@pytest.fixture
def routes(tmp_path):
    store = ThreadSafeStore(tmp_path / "db.sqlite")
    factory = ControlledFactory()
    orch = Orchestrator(store, settings(tmp_path / "data", attachment_max_bytes=16),
                        factory, lambda harness, sid, cwd: True, human_id="local")
    for name in ["alpha", "beta"]:
        orch.put_agent(Agent(name, name, name, name + " specialist", "codex", "", "help"))
    channel = orch.create_channel("test", agent_ids=["alpha", "beta"], primary_agent_id="alpha")
    with TestClient(_with_peer(create_app(orch)), base_url="http://127.0.0.1") as client:
        yield client, orch, factory, channel.channel_id
    store.close()


def wait_for_run(client, cid, count):
    for _ in range(400):
        runs = client.get(f"/channels/{cid}/runs").json()
        if len(runs) >= count and runs[-1]["status"] in {"starting", "running"}:
            return runs
    pytest.fail("run did not start")


def test_channel_handoff_setting_and_authoritative_routing_state(routes):
    client, _, _, cid = routes
    assert client.patch(f"/channels/{cid}", json={"allow_handoff": False}).json()["allow_handoff"] is False
    assert client.patch(f"/channels/{cid}", json={}).status_code == 422
    client.post(f"/channels/{cid}/messages", json={"text": "Code", "mentions": ["alpha"]})
    summary = next(c for c in client.get("/channels").json() if c["channel_id"] == cid)
    assert summary["primary_agent_id"] == "alpha" and summary["ownership_version"] == 1
    assert summary["routing_mode"] == "primary" and summary["active_task_agent_ids"] == ["alpha"]
    assert summary["allow_handoff"] is False


def test_focus_mode_is_saved_per_channel_and_dm_and_broadcast_to_clients(routes):
    client, orch, _, cid = routes
    dm = orch.store.get_agent("alpha").dm_channel_id
    assert orch.store.get_channel(cid).focus_mode is False
    assert orch.store.get_channel(dm).focus_mode is False
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"last_id": 0})
        response = client.patch(f"/channels/{dm}", json={"focus_mode": True})
        assert response.status_code == 200 and response.json()["focus_mode"] is True
        frame = socket.receive_json()
        while not (frame["type"] == "event" and frame["event"]["kind"] == "channel_changed"
                   and frame["event"]["channel_id"] == dm):
            frame = socket.receive_json()
        assert frame["event"]["payload"]["focus_mode"] is True
        while not (frame["type"] == "channel_summary" and frame["channel_id"] == dm and frame["focus_mode"]):
            frame = socket.receive_json()
        assert frame["focus_mode"] is True
    summaries = {c["channel_id"]: c for c in client.get("/channels").json()}
    assert summaries[cid]["focus_mode"] is False and summaries[dm]["focus_mode"] is True
    assert client.patch(f"/channels/{dm}", json={"focus_mode": False}).json()["focus_mode"] is False
    assert client.patch(f"/channels/{cid}", json={"focus_mode": None}).status_code == 422


def test_attachment_upload_download_send_and_delete(routes):
    client, _, _, cid = routes
    uploaded = client.post(f"/channels/{cid}/attachments", params={"filename": "page.html"},
                           content=b"<script>", headers={"content-type": "text/html"})
    assert uploaded.status_code == 201, uploaded.text
    meta = uploaded.json()
    assert meta["filename"] == "page.html" and meta["message_seq"] is None
    assert meta["url"] == f"/attachments/{meta['attachment_id']}"
    assert "path" not in meta

    download = client.get(meta["url"])
    assert download.content == b"<script>"
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["content-security-policy"] == "sandbox"

    image = client.post(f"/channels/{cid}/attachments", params={"filename": "a.png"},
                        content=b"png", headers={"content-type": "image/png"}).json()
    assert client.get(image["url"]).headers["content-disposition"].startswith("inline;")

    sent = client.post(f"/channels/{cid}/messages",
                       json={"attachments": [meta["attachment_id"]], "mentions": ["alpha"]})
    assert sent.status_code == 201, sent.text
    assert sent.json()["payload"]["attachments"][0]["attachment_id"] == meta["attachment_id"]
    assert client.get(meta["url"] + "/meta").json()["message_seq"] == sent.json()["seq"]
    assert client.delete(meta["url"]).status_code == 400
    assert client.delete(image["url"]).status_code == 204
    assert client.get(image["url"]).status_code == 404


def test_attachment_size_limit_and_empty_messages(routes):
    client, orch, _, cid = routes
    too_big = client.post(f"/channels/{cid}/attachments", params={"filename": "big.bin"}, content=b"x" * 17)
    assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "too_large"

    def chunked():
        yield b"x" * 10
        yield b"x" * 10

    streamed = client.post(f"/channels/{cid}/attachments", params={"filename": "big.bin"}, content=chunked())
    assert streamed.status_code == 413
    assert not any(orch.settings.attachment_dir.iterdir())
    assert client.post(f"/channels/{cid}/messages", json={"text": ""}).status_code == 422


def test_cwd_member_and_queue_routes(routes, tmp_path):
    client, _, factory, cid = routes
    moved = client.put(f"/channels/{cid}/cwd", json={"cwd": str(tmp_path)})
    assert moved.status_code == 200 and moved.json()["cwd"] == str(tmp_path)
    assert client.put(f"/channels/{cid}/cwd", json={"cwd": str(tmp_path / "nope")}).status_code == 400
    assert client.put(f"/channels/{cid}/cwd", json={}).status_code == 422
    managed = client.put(f"/channels/{cid}/cwd", json={"cwd": None}).json()
    assert managed["cwd_managed"] is True

    client.post(f"/channels/{cid}/messages", json={"text": "work", "mentions": ["alpha"]})
    wait_for_run(client, cid, 1)
    assert client.put(f"/channels/{cid}/cwd", json={"cwd": str(tmp_path)}).status_code == 400
    queued = client.post(f"/channels/{cid}/messages", json={"text": "later", "mentions": ["alpha"]}).json()
    assert [(i["event_seq"], i["agent_id"]) for i in client.get(f"/channels/{cid}/queue").json()] == [
        (queued["seq"], "alpha"),
    ]
    cancelled = client.post(f"/channels/{cid}/messages/{queued['seq']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["payload"]["retracted"] is True
    assert client.get(f"/channels/{cid}/queue").json() == []
    assert client.post(f"/channels/{cid}/messages/{queued['seq']}/cancel").status_code == 400

    removed = client.delete(f"/channels/{cid}/members/alpha")
    assert removed.status_code == 200
    assert [m["member_id"] for m in removed.json() if m["member_kind"] == "agent"] == ["beta"]
    assert client.delete(f"/channels/{cid}/members/alpha").status_code == 404
    assert factory.started[0].cancelled


def test_websocket_cancel_delivery_and_queue_snapshot(routes):
    client, _, _, cid = routes
    client.post(f"/channels/{cid}/messages", json={"text": "work", "mentions": ["alpha"]})
    wait_for_run(client, cid, 1)
    queued = client.post(f"/channels/{cid}/messages", json={"text": "later", "mentions": ["alpha"]}).json()
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"last_id": queued["id"]})
        snapshot = socket.receive_json()
        while snapshot["type"] != "queue":
            snapshot = socket.receive_json()
        assert snapshot["type"] == "queue" and snapshot["items"][0]["event_seq"] == queued["seq"]
        socket.send_json({"type": "cancel_delivery", "channel_id": cid, "target_seq": queued["seq"],
                          "agent_ids": ["alpha"]})
        frames = []
        while len(frames) < 3:
            frame = socket.receive_json()
            if frame["type"] in {"event", "queue"}:
                frames.append(frame)
        assert [f.get("event", {}).get("kind", f["type"]) for f in frames] == [
            "delivery_cancelled", "message_edit", "queue",
        ]
        assert frames[2]["items"] == []
