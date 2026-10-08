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
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        pass
                    await asyncio.sleep(0.05)
            assert health.json() == {"status": "ok"}
            response = await client.post(base + "/channels", json={"name": "smoke"})
            assert response.status_code == 201, response.text
            cid = response.json()["channel_id"]
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws", proxy=None) as ws:
                await ws.send(json.dumps({"last_id": 0}))
                initial = []
                while True:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    initial.append(frame)
                    if frame["type"] == "me":
                        break
                assert any(frame["type"] == "channel_summary" and frame["channel_id"] == cid
                           for frame in initial)
                await ws.send(json.dumps({"type": "send_message", "channel_id": cid, "text": "hello"}))
                frames = []
                while True:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    frames.append(frame)
                    if frame["type"] == "queue" and frame["items"] == []:
                        break
                events = [frame for frame in frames if frame["type"] == "event"]
                assert [frame["event"]["kind"] for frame in events] == ["message", "routing_decision"]
                message, routing = events
                assert message["event"]["kind"] == "message"
                assert routing["event"]["kind"] == "routing_decision"
                assert routing["event"]["payload"]["agents"] == []
                assert routing["event"]["payload"]["reason_code"] == "none"
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
