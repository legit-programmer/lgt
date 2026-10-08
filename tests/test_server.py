from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest
import websockets

from lgt.processes import spawn_command


async def drain(stream):
    captured = bytearray()
    while data := await stream.read(65536):
        if len(captured) < 65536:
            captured.extend(data[:65536 - len(captured)])
    return captured.decode("utf-8", errors="replace")


@pytest.mark.asyncio
async def test_native_server_boot_http_websocket_and_replay_without_model_calls(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    raw = json.loads((repo / "config.example.json").read_text(encoding="utf-8"))
    raw["settings"]["data_dir"] = str(tmp_path / "data")
    config = tmp_path / "config.json"
    config.write_text(json.dumps(raw), encoding="utf-8")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    tree = await spawn_command(
        [sys.executable, "-m", "lgt", "--config", str(config), "--port", str(port)],
        str(repo), line_limit=1048576,
    )
    stdout = asyncio.create_task(drain(tree.process.stdout))
    stderr = asyncio.create_task(drain(tree.process.stderr))
    try:
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            async with asyncio.timeout(15):
                while True:
                    if tree.process.returncode is not None:
                        pytest.fail("server exited at startup: " + await stderr)
                    try:
                        health = await client.get(base + "/health")
                        if health.status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(0.05)
            assert health.json() == {"status": "ok"}
            response = await client.post(base + "/channels", json={"name": "smoke"})
            assert response.status_code == 201, response.text
            cid = response.json()["channel_id"]
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws", proxy=None) as ws:
                await ws.send(json.dumps({"last_id": 0}))
                await ws.send(json.dumps({"type": "send_message", "channel_id": cid, "text": "hello"}))
                frames = [json.loads(await asyncio.wait_for(ws.recv(), 5)) for _ in range(4)]
                # Queue frames report the pending routing delivery between events.
                assert [frame["type"] for frame in frames] == ["event", "queue", "event", "queue"]
                message, routing = frames[0], frames[2]
                assert message["event"]["kind"] == "message"
                assert routing["event"]["kind"] == "routing_decision"
                assert routing["event"]["payload"]["agents"] == []
                assert "no agent members" in routing["event"]["payload"]["reason"]
            history = (await client.get(base + f"/channels/{cid}/events")).json()
            assert [event["seq"] for event in history] == [1, 2]
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws", proxy=None) as ws:
                await ws.send(json.dumps({"last_id": message["event"]["id"]}))
                replay = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert replay["event"] == routing["event"]
    finally:
        await tree.terminate(1)
        await tree.close()
        await asyncio.gather(stdout, stderr)
