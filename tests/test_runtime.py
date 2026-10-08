from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from lgt.models import Agent
from lgt.runtime import BackendRuntime, RuntimeConfig, application, load_config
from tests.support import settings


def config_file(tmp_path, **extra):
    values = asdict(settings(tmp_path / "data"))
    values["data_dir"] = "data"
    values.pop("route_after_active")
    raw = {"settings": values, "checkpoint_mode": "deferred", **extra}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_runtime_loads_explicit_settings_and_immediate_routing(tmp_path):
    config = load_config(config_file(tmp_path))
    assert config.settings.data_dir == tmp_path / "data"
    assert not config.settings.route_after_active
    assert config.checkpoint_mode == "deferred"


def test_configuration_cannot_choose_old_hold_routing(tmp_path):
    path = config_file(tmp_path)
    raw = json.loads(path.read_text())
    raw["settings"]["route_after_active"] = True
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="fixed to false"):
        load_config(path)


def test_settings_and_checkpoint_selection_have_no_implicit_defaults(tmp_path):
    path = config_file(tmp_path)
    raw = json.loads(path.read_text())
    raw["settings"].pop("concurrent_runs")
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="concurrent_runs"):
        load_config(path)
    path = config_file(tmp_path)
    raw = json.loads(path.read_text())
    raw.pop("checkpoint_mode")
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="checkpoint_mode"):
        load_config(path)


def test_configuration_rejects_boolean_run_limit(tmp_path):
    path = config_file(tmp_path)
    raw = json.loads(path.read_text())
    raw["settings"]["concurrent_runs"] = True
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="concurrent_runs"):
        load_config(path)


def test_real_runtime_http_and_ws_use_database_on_server_thread(tmp_path, monkeypatch):
    async def probe(self):
        return {"version": "fixture", "capabilities": {"app_server": True}}

    monkeypatch.setattr("lgt.runtime.CodexAppServerRunner.probe", probe)
    async def forbidden_cli(*args, **kwargs):
        pytest.fail("empty channels must not invoke a model CLI")
    monkeypatch.setattr("lgt.runtime.make_cli_invoker", lambda **kwargs: forbidden_cli)
    app = application(config_file(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 42000)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        # No agent is seeded and this empty channel does not call either router CLI.
        channel = client.post("/channels", json={"name": "general"}).json()
        cid = channel["channel_id"]
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"last_id": 0})
            socket.send_json({"type": "send_message", "channel_id": cid, "text": "hello"})
            # Queue frames report the pending routing delivery between events.
            frames = [socket.receive_json() for _ in range(4)]
            assert [f["type"] for f in frames] == ["event", "queue", "event", "queue"]
            assert frames[1]["items"][0]["state"] == "awaiting_route" and frames[3]["items"] == []
            human, routing = frames[0], frames[2]
            assert human["event"]["payload"]["text"] == "hello"
            assert routing["event"]["kind"] == "routing_decision"
            assert routing["event"]["payload"]["agents"] == []
        events = client.get(f"/channels/{cid}/events").json()
        assert [e["seq"] for e in events] == [1, 2]
    # Runtime shutdown releases its lock and retains its durable log.
    second = application(tmp_path / "config.json")
    with TestClient(second, base_url="http://127.0.0.1", client=("127.0.0.1", 42000)) as client:
        assert client.get(f"/channels/{cid}/events").json() == events


@pytest.mark.asyncio
async def test_runtime_keeps_one_writer_and_recovers_after_releasing_lock(tmp_path, monkeypatch):
    async def probe(self):
        return {"version": "fixture", "capabilities": {}}

    monkeypatch.setattr("lgt.runtime.CodexAppServerRunner.probe", probe)
    config = RuntimeConfig(settings(tmp_path), "deferred")
    first, second = BackendRuntime(config), BackendRuntime(config)
    await first.start()
    try:
        with pytest.raises(RuntimeError, match="another backend"):
            await second.start()
    finally:
        await first.close()
    await second.start()
    await second.close()
