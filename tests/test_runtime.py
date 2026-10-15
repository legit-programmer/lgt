from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from lgt.models import Agent
from lgt.runtime import BackendRuntime, RuntimeConfig, application, load_config
from tests.support import settings


FIXTURE = str(Path(__file__).with_name("fake_streaming_cli.py"))


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


@pytest.mark.parametrize("key,value", [
    ("listen_host", "attacker.example"), ("listen_host", []),
    ("listen_port", True), ("listen_port", -1), ("listen_port", 65536),
    ("advertised_url", "http://user:secret@host"), ("advertised_url", "http://host/path"),
    ("advertised_url", "http://0.0.0.0:8000"), ("advertised_url", "http://host:0"),
    ("advertised_url", "http://host?token=secret"), ("advertised_url", "file:///tmp"),
])
def test_remote_connection_configuration_is_validated(tmp_path, key, value):
    path = config_file(tmp_path)
    raw = json.loads(path.read_text())
    raw["settings"][key] = value
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match=key):
        load_config(path)


def test_remote_configuration_keeps_old_configs_compatible(tmp_path):
    path = config_file(tmp_path)
    raw = json.loads(path.read_text())
    for key in ("listen_host", "listen_port", "advertised_url"):
        raw["settings"].pop(key)
    path.write_text(json.dumps(raw))
    config = load_config(path)
    assert config.settings.listen_host == "127.0.0.1"
    assert config.settings.listen_port == 8000
    assert config.settings.advertised_url is None
    raw["settings"].update(listen_host="0.0.0.0", listen_port=9000, advertised_url="https://lgt.example/")
    path.write_text(json.dumps(raw))
    assert load_config(path).settings.advertised_url == "https://lgt.example"


def test_real_runtime_http_and_ws_use_database_on_server_thread(tmp_path, monkeypatch):
    async def probe(self):
        return {"version": "fixture", "capabilities": {"app_server": True}}

    monkeypatch.setattr("lgt.runtime.CodexAppServerRunner.probe", probe)
    async def forbidden_cli(*args, **kwargs):
        pytest.fail("empty channels must not invoke a model CLI")
    monkeypatch.setattr("lgt.runtime.make_cli_invoker", lambda **kwargs: forbidden_cli)
    app = application(config_file(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 42000)) as client:
        assert client.get("/health").json()["application"] == "lgt"
        # No agent is seeded and this empty channel does not call either router CLI.
        channel = client.post("/channels", json={"name": "general"}).json()
        cid = channel["channel_id"]
        with client.websocket_connect("/ws", headers={"host": "127.0.0.1"}) as socket:
            socket.send_json({"last_id": 0})
            initial = []
            while True:
                frame = socket.receive_json()
                initial.append(frame)
                if frame["type"] == "me":
                    break
            assert any(frame["type"] == "channel_summary" and frame["channel_id"] == cid
                       for frame in initial)
            socket.send_json({"type": "send_message", "channel_id": cid, "text": "hello"})
            frames = []
            while True:
                frame = socket.receive_json()
                frames.append(frame)
                if frame["type"] == "queue" and frame["items"] == []:
                    break
            events = [frame for frame in frames if frame["type"] == "event"]
            queues = [frame for frame in frames if frame["type"] == "queue"]
            assert queues[0]["items"][0]["state"] == "awaiting_route"
            human, routing = events
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



@pytest.mark.asyncio
async def test_runtime_probes_custom_agents_after_restart(tmp_path, monkeypatch):
    async def probe(self):
        return {"version": "fixture", "capabilities": {}}

    monkeypatch.setattr("lgt.runtime.CodexAppServerRunner.probe", probe)
    monkeypatch.setenv("LGT_FAKE_HARNESS", "custom")
    scripts = {handle: tmp_path / f"{handle}.py" for handle in ("good", "broken")}
    for script in scripts.values():
        shutil.copy(FIXTURE, script)
    config = RuntimeConfig(settings(tmp_path), "deferred")
    first = BackendRuntime(config)
    await first.start()
    try:
        for handle, script in scripts.items():
            agent = Agent(handle, handle, handle, "Helper", "custom", "auto", "Help",
                          avatar={"style": "bottts", "seed": handle}, command=[sys.executable, str(script)])
            await first.harness_registry.prepare_agent(agent)
            first.put_agent(agent)
    finally:
        await first.close()

    # The probe cache is empty after a restart, and one agent's command no longer works.
    scripts["broken"].unlink()
    second = BackendRuntime(config)
    await second.start()
    try:
        dms = {second.store.get_agent(handle).dm_channel_id: handle for handle in scripts}
        frames = second.snapshot_frames(set(dms))
        assert {dms[f["channel_id"]] for f in frames if f["type"] == "context"} == {"good"}
        assert any(f["type"] == "usage" for f in frames)
    finally:
        await second.close()
