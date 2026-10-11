from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lgt.daemon import DaemonState
from lgt.gateway import create_app
from tests.test_gateway import FakeOrchestrator


def remote_app(tmp_path):
    orch = FakeOrchestrator(tmp_path)
    orch.settings.listen_host = "0.0.0.0"
    orch.settings.advertised_url = "https://lgt.example"
    orch.settings.allowed_origins = ("tauri://localhost",)
    daemon = DaemonState(tmp_path)
    app = create_app(orch, daemon=daemon)

    async def transport(scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            scope = dict(scope)
            # Simulate independent TCP peers within the same server event loop.
            headers = dict(scope["headers"])
            peer = headers.get(b"x-test-peer", b"127.0.0.1").decode()
            scope["client"] = (peer, 42000)
            if scope["type"] == "websocket":
                scope["headers"] = [(k, v) for k, v in scope["headers"] if k != b"host"] + [(b"host", b"lgt.example")]
        await app(scope, receive, send)

    return transport, orch, daemon


def bearer(token, *, remote=False):
    return {"Authorization": "Bearer " + token, **({"x-test-peer": "203.0.113.10"} if remote else {})}


def pair(client, daemon, name="iPhone"):
    response = client.post("/devices", json={"name": name}, headers=bearer(daemon.token))
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_pairing_credentials_are_named_hashed_and_persist_across_restart(tmp_path):
    app, orch, daemon = remote_app(tmp_path)
    with TestClient(app, base_url="https://lgt.example") as client:
        paired = pair(client, daemon, "  iPhone  ")
        pairing = paired["pairing"]
        token = pairing["token"]
        device_id = pairing["device_id"]
        assert pairing == {"type": "lgt-device", "version": 1, "url": "https://lgt.example",
                           "device_id": device_id, "name": "iPhone", "token": token}
        row = orch.store.conn.execute("SELECT * FROM devices").fetchone()
        assert row["credential_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in json.dumps(dict(row))
        assert client.get("/connection", headers=bearer(token, remote=True)).json() == {
            "device_id": device_id, "local_admin": False,
        }
        devices = client.get("/devices", headers=bearer(daemon.token)).json()
        assert devices[0]["last_used_at"] is not None
        assert token not in json.dumps(devices)
        assert "credential_hash" not in devices[0]
        renamed = client.patch(f"/devices/{device_id}", json={"name": "Work phone"}, headers=bearer(daemon.token))
        assert renamed.json()["name"] == "Work phone"
    app, _, restarted = remote_app(tmp_path)
    assert restarted.token != daemon.token
    with TestClient(app, base_url="https://lgt.example") as client:
        assert client.get("/health", headers=bearer(token, remote=True)).status_code == 200
        assert client.get("/devices", headers=bearer(restarted.token)).json()[0]["name"] == "Work phone"


def test_remote_http_and_ws_require_device_credentials_and_approved_origins(tmp_path):
    app, _, daemon = remote_app(tmp_path)
    with TestClient(app, base_url="https://lgt.example") as client:
        paired = pair(client, daemon)
        token = paired["pairing"]["token"]
        for credential in (None, "wrong", daemon.token):
            headers = bearer(credential, remote=True) if credential else {"x-test-peer": "203.0.113.10"}
            assert client.get("/health", headers=headers).status_code == 401
            assert client.get("/docs", headers=headers).status_code == 401
            assert client.get("/attachments/missing", headers=headers).status_code == 401
            with client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.10"}) as ws:
                ws.send_json({"last_id": 0, "token": credential})
                with pytest.raises(WebSocketDisconnect) as closed:
                    ws.receive_json()
                assert closed.value.code == 1008
        headers = bearer(token, remote=True)
        assert client.get("/channels", headers=headers).status_code == 200
        assert client.get("/health", headers={**headers, "Origin": "https://attacker.example"}).status_code == 403
        response = client.get("/health", headers={**headers, "Origin": "tauri://localhost"})
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == "tauri://localhost"
        assert client.options("/health", headers={"x-test-peer": "203.0.113.10", "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}).status_code == 204
        with client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.10", "Origin": "tauri://localhost"}) as ws:
            ws.send_json({"last_id": 0, "token": token})
            ws.send_json({"type": "send_message", "channel_id": client.get("/channels", headers=headers).json()[0]["channel_id"], "text": "from phone"})
            assert ws.receive_json()["event"]["payload"]["text"] == "from phone"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.10", "Origin": "https://attacker.example"}):
                pass


def test_device_administration_is_local_token_only_and_ignores_forwarded_headers(tmp_path):
    app, _, daemon = remote_app(tmp_path)
    with TestClient(app, base_url="https://lgt.example") as client:
        paired = pair(client, daemon)
        token, did = paired["pairing"]["token"], paired["device"]["device_id"]
        for headers in (bearer(token, remote=True), bearer(token), {
            **bearer(daemon.token, remote=True), "Host": "localhost", "X-Forwarded-For": "127.0.0.1",
            "Forwarded": "for=127.0.0.1;host=localhost",
        }):
            assert client.get("/devices", headers=headers).status_code in {401, 403}
            assert client.post("/devices", json={"name": "Intruder"}, headers=headers).status_code in {401, 403}
            assert client.patch(f"/devices/{did}", json={"name": "Intruder"}, headers=headers).status_code in {401, 403}
            assert client.post(f"/devices/{did}/revoke", headers=headers).status_code in {401, 403}
            assert client.post("/shutdown", headers=headers).status_code in {401, 403}
        assert client.get("/connection", headers=bearer(daemon.token)).json()["local_admin"] is True
        assert client.get("/health", headers=bearer(token, remote=True)).status_code == 200


def test_revoke_disconnects_every_socket_for_device_without_affecting_other_clients(tmp_path):
    app, _, daemon = remote_app(tmp_path)
    with TestClient(app, base_url="https://lgt.example") as client:
        first, second = pair(client, daemon), pair(client, daemon, "Other desktop")
        token, did = first["pairing"]["token"], first["device"]["device_id"]
        with client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.10"}) as ws1, \
             client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.11"}) as ws2, \
             client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.12"}) as other:
            for ws, credential in ((ws1, token), (ws2, token), (other, second["pairing"]["token"])):
                ws.send_json({"last_id": 0, "token": credential})
                # An invalid command provides a response after replay has completed.
                ws.send_json({"type": "unknown"})
                assert ws.receive_json()["type"] == "error"
            revoked = client.post(f"/devices/{did}/revoke", headers=bearer(daemon.token)).json()
            assert revoked["revoked_at"] is not None
            for ws in (ws1, ws2):
                with pytest.raises(WebSocketDisconnect) as closed:
                    ws.receive_json()
                assert closed.value.code == 1008
            other.send_json({"type": "unknown"})
            assert other.receive_json()["type"] == "error"
        assert client.get("/health", headers=bearer(token, remote=True)).status_code == 401
        assert client.get("/health", headers=bearer(second["pairing"]["token"], remote=True)).status_code == 200
        assert client.post(f"/devices/{did}/revoke", headers=bearer(daemon.token)).json() == revoked
        with client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.10"}) as ws:
            ws.send_json({"last_id": 0, "token": token})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    app, _, restarted = remote_app(tmp_path)
    with TestClient(app, base_url="https://lgt.example") as client:
        assert client.get("/health", headers=bearer(token, remote=True)).status_code == 401
        assert client.get("/devices", headers=bearer(restarted.token)).json()[0]["revoked_at"] is not None


def test_clients_receive_shared_events_and_replay_after_reconnecting(tmp_path):
    app, orch, daemon = remote_app(tmp_path)
    with TestClient(app, base_url="https://lgt.example") as client:
        phone, desktop = pair(client, daemon), pair(client, daemon, "Desktop")
        channel_id = orch.store.list_channels()[0].channel_id
        with client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.10"}) as first, \
             client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.11"}) as second:
            for ws, pairing in ((first, phone["pairing"]), (second, desktop["pairing"])):
                ws.send_json({"last_id": 0, "token": pairing["token"]})
                ws.send_json({"type": "unknown"})
                assert ws.receive_json()["type"] == "error"
            message = client.post(f"/channels/{channel_id}/messages", json={"text": "shared"},
                                  headers=bearer(phone["pairing"]["token"], remote=True)).json()
            assert first.receive_json()["event"]["id"] == message["id"]
            assert second.receive_json()["event"]["id"] == message["id"]
        later = client.post(f"/channels/{channel_id}/messages", json={"text": "while disconnected"},
                            headers=bearer(desktop["pairing"]["token"], remote=True)).json()
        with client.websocket_connect("/ws", headers={"x-test-peer": "203.0.113.10"}) as reconnect:
            reconnect.send_json({"last_id": message["id"], "token": phone["pairing"]["token"]})
            assert reconnect.receive_json()["event"]["id"] == later["id"]


def test_pairing_validates_name_and_does_not_create_without_configuration(tmp_path):
    app, orch, daemon = remote_app(tmp_path)
    with TestClient(app, base_url="https://lgt.example") as client:
        for body in ({"name": " "}, {"name": "\n"}, {"name": "x" * 101}, {"name": "Phone", "token": "chosen"}):
            assert client.post("/devices", json=body, headers=bearer(daemon.token)).status_code in {400, 422}
        orch.settings.advertised_url = None
        assert client.post("/devices", json={"name": "Phone"}, headers=bearer(daemon.token)).status_code == 409
        assert client.get("/devices", headers=bearer(daemon.token)).json() == []


def test_remote_gateway_cannot_start_without_authentication(tmp_path):
    orch = FakeOrchestrator(tmp_path)
    orch.settings.listen_host = "0.0.0.0"
    try:
        with pytest.raises(ValueError, match="authenticated daemon"):
            create_app(orch)
    finally:
        orch.store.close()
