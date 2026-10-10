from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import websockets
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lgt.daemon import DaemonState
from lgt.gateway import create_app
from lgt.processes import spawn_command
from tests.test_gateway import FakeOrchestrator, _with_peer


def test_descriptor_is_private_atomic_and_only_removed_by_owner(tmp_path):
    state = DaemonState(tmp_path)
    state.publish(43123)
    descriptor = json.loads(state.path.read_text())
    assert descriptor["token"] == state.token
    assert descriptor["pid"] == os.getpid()
    assert descriptor["port"] == 43123
    if os.name != "nt":
        assert state.path.stat().st_mode & 0o777 == 0o600
    other = DaemonState(tmp_path)
    other.remove()
    assert state.path.exists()
    state.remove()
    assert not state.path.exists()
    assert not list(tmp_path.glob(".daemon-*.tmp"))


def test_daemon_requires_token_before_http_or_socket_state(tmp_path):
    state = DaemonState(tmp_path)
    orch = FakeOrchestrator(tmp_path)
    orch.settings.allowed_origins = ("tauri://localhost",)
    channel = orch.store.list_channels()[0]
    orch.store.append_event(channel.channel_id, "message", "human", "local", {"text": "private history"})
    with TestClient(_with_peer(create_app(orch, daemon=state)), base_url="http://127.0.0.1") as client:
        assert client.get("/health").status_code == 401
        assert client.get("/agents", headers={"Authorization": "Bearer wrong"}).status_code == 401
        authorized = {"Authorization": "Bearer " + state.token}
        assert client.get("/health", headers=authorized).json()["pid"] == os.getpid()
        response = client.options("/health", headers={
            "Origin": "tauri://localhost", "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        })
        assert response.status_code == 204
        assert "Authorization" in response.headers["Access-Control-Allow-Headers"]
        for token in (None, "wrong", "☃"):
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"last_id": 0, **({"token": token} if token else {})})
                with pytest.raises(WebSocketDisconnect) as error:
                    ws.receive_json()
                assert error.value.code == 1008
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"last_id": 0, "token": state.token})
            assert ws.receive_json()["type"] in {"event", "channel_summary", "me", "agent_status"}
        requested = []
        state.request_shutdown = lambda: requested.append(True)
        assert client.post("/shutdown").status_code == 401
        assert not requested
        assert client.post("/shutdown", headers=authorized).json() == {"status": "stopping"}
        assert requested == [True]


@pytest.mark.asyncio
async def test_daemon_subprocess_discovery_duplicate_lock_and_graceful_shutdown(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    raw = json.loads((repo / "config.example.json").read_text(encoding="utf-8"))
    data_dir = tmp_path / "data"
    raw["settings"]["data_dir"] = str(data_dir)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(raw), encoding="utf-8")
    argv = [sys.executable, "-m", "lgt", "--config", str(config), "--port", "0", "--daemon"]
    tree = await spawn_command(argv, str(repo), line_limit=1048576)
    duplicate = None
    try:
        async with asyncio.timeout(20):
            while not (data_dir / "daemon.json").exists():
                if tree.process.returncode is not None:
                    pytest.fail("daemon failed: " + (data_dir / "logs/daemon.log").read_text())
                await asyncio.sleep(0.05)
        descriptor = json.loads((data_dir / "daemon.json").read_text())
        # Windows virtualenv Python is a launcher; the serving process has its own PID.
        assert descriptor["pid"] > 0
        assert descriptor["api_version"] == 1
        assert 0 < descriptor["port"] < 65536
        base = f'http://127.0.0.1:{descriptor["port"]}'
        token = descriptor["token"]
        headers = {"Authorization": "Bearer " + token}
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            assert (await client.get(base + "/health")).status_code == 401
            health = await client.get(base + "/health", headers=headers)
            assert health.json() == {"status": "ok", "application": "lgt", "api_version": 1, "pid": descriptor["pid"]}
            duplicate = await spawn_command(argv, str(repo), line_limit=1048576)
            assert await asyncio.wait_for(duplicate.process.wait(), 15) != 0
            assert json.loads((data_dir / "daemon.json").read_text()) == descriptor
            async with websockets.connect(base.replace("http:", "ws:") + "/ws", proxy=None) as ws:
                await ws.send(json.dumps({"last_id": 0, "token": token}))
                assert json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] in {"usage", "me"}
            assert (await client.post(base + "/shutdown", headers=headers)).status_code == 200
            assert await asyncio.wait_for(tree.process.wait(), 15) == 0
        assert not (data_dir / "daemon.json").exists()
        log = (data_dir / "logs/daemon.log").read_text(encoding="utf-8")
        assert "Application startup complete" in log
        assert token not in log
    finally:
        if duplicate is not None:
            await duplicate.terminate(1)
            await duplicate.close()
        await tree.terminate(1)
        await tree.close()
