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
    raw = {"settings": values, "checkpoint_mode": "deferred", **extra}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_runtime_loads_explicit_settings_without_router_configuration(tmp_path):
    config = load_config(config_file(tmp_path))
    assert config.settings.data_dir == tmp_path / "data"
    assert config.settings.startup_timeout_seconds == 1
    assert config.settings.checkpoint_timeout_seconds == 1
    assert config.checkpoint_mode == "deferred"


def test_legacy_router_configuration_only_maps_to_checkpoint_and_startup(tmp_path):
    path = config_file(tmp_path)
    raw = json.loads(path.read_text())
    values = raw["settings"]
    values.pop("startup_timeout_seconds")
    values.pop("checkpoint_timeout_seconds")
    values.pop("checkpoint_claude_model")
    values.pop("checkpoint_codex_model")
    values.pop("checkpoint_attempts")
    values.update(
        router_timeout_seconds=4.5,
        router_context_events=50,
        router_model="legacy-model",
        codex_router_model="legacy-codex-model",
        router_attempts=3,
        route_after_active=False,
    )
    raw["codex_router_command"] = ["codex", "--legacy"]
    path.write_text(json.dumps(raw))
    config = load_config(path)
    assert config.settings.startup_timeout_seconds == 4.5
    assert config.settings.checkpoint_timeout_seconds == 4.5
    assert config.settings.checkpoint_claude_model == "legacy-model"
    assert config.settings.checkpoint_codex_model == "legacy-codex-model"
    assert config.settings.checkpoint_attempts == 3
    assert config.codex_checkpoint_command == ("codex", "--legacy")


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
    path = config_file(tmp_path)
    raw = json.loads(path.read_text())
    raw["settings"].pop("startup_timeout_seconds")
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="startup_timeout_seconds"):
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


def test_real_runtime_starts_without_router_or_checkpoint_cli(tmp_path, monkeypatch):
    async def probe(self):
        return {"version": "fixture", "capabilities": {"app_server": True}}

    monkeypatch.setattr("lgt.runtime.CodexAppServerRunner.probe", probe)
    monkeypatch.setattr(
        "lgt.runtime.make_cli_invoker",
        lambda **kwargs: pytest.fail("deferred checkpoints must not create a model CLI invoker"),
    )
    app = application(config_file(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 42000)) as client:
        assert client.get("/health").json()["application"] == "lgt"


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
