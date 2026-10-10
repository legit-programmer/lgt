from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lgt.broadcast import EventBus
from lgt.gateway import create_app
from lgt.models import Agent, Channel, Event, Run, WorkspaceError, new_id
from lgt.store import Store


class FakeBus(EventBus):
    def __init__(self):
        super().__init__()
        self.channel_updates: list[set[str]] = []

    def update_channels(self, channel_ids: set[str]) -> None:
        self.channel_updates.append(set(channel_ids))
        for subscription in tuple(self._subscriptions):
            subscription.channel_ids = set(channel_ids)


class FakeOrchestrator:
    def __init__(self, data_dir: Path):
        self.human_id = "local"
        self.settings = SimpleNamespace(replay_cap=32, attachment_max_bytes=1024)
        self.store = ThreadSafeStore(data_dir / "gateway.sqlite3")
        self.bus = FakeBus()
        self.started = False
        self.closed = False
        self.cancelled: list[str] = []
        self.snapshots: list[dict[str, Any]] = []
        self.duplicate_during_replay = False
        self.put_agent(Agent(
            agent_id="a1",
            handle="builder",
            name="Builder",
            description="Writes code",
            harness="codex",
            model="gpt-5-codex",
            system_prompt="Help with code.",
        ))
        self.create_channel("general", agent_ids=["a1"], cwd=str(data_dir))

        store_replay = self.store.replay

        def replay_and_duplicate(last_id: int, channel_ids: list[str], limit: int):
            events = store_replay(last_id, channel_ids, limit)
            if self.duplicate_during_replay and events:
                self.bus.publish({"type": "event", "event": events[0].to_dict()})
                self.duplicate_during_replay = False
            return events

        self.store.replay = replay_and_duplicate

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True
        self.store.close()

    def put_agent(self, agent: Agent) -> None:
        if agent.harness != "codex":
            raise WorkspaceError("Only the Codex harness is supported.")
        self.store.put_agent(agent)

    def create_channel(
        self,
        name: str,
        kind: str = "channel",
        agent_ids: list[str] | None = None,
        cwd: str | None = None,
    ) -> Channel:
        channel = Channel(
            channel_id=new_id(),
            kind=kind,
            name=name,
            cwd=cwd or ".",
            cwd_managed=cwd is None,
        )
        members = [("human", self.human_id)]
        members.extend(("agent", agent_id) for agent_id in agent_ids or [])
        self.store.create_channel(channel, members)
        return channel

    def add_member(self, channel_id: str, agent_id: str) -> None:
        self.store.add_member(channel_id, "agent", agent_id)

    def _ensure_member(self, channel_id: str) -> None:
        if not any(
            member["member_kind"] == "human" and member["member_id"] == self.human_id
            for member in self.store.members(channel_id)
        ):
            raise WorkspaceError("Human is not a member of this channel.")

    async def send_message(self, channel_id: str, text: str, mentions=None, attachments=None) -> Event:
        self._ensure_member(channel_id)
        event = self.store.append_event(
            channel_id,
            "message",
            "human",
            self.human_id,
            {"text": text, "mentions": mentions or []},
        )
        self.bus.publish({"type": "event", "event": event.to_dict()})
        return event

    async def edit_message(self, channel_id: str, target_seq: int, text=None, deleted=None) -> Event:
        self._ensure_member(channel_id)
        target = self.store.get_event(channel_id, target_seq)
        if target.kind != "message" or target.author_kind != "human":
            raise WorkspaceError("Only human messages can be edited.")
        event = self.store.append_event(
            channel_id,
            "message_edit",
            "human",
            self.human_id,
            {"target_seq": target_seq, "text": text, "deleted": deleted},
            chain_id=target.chain_id,
        )
        self.bus.publish({"type": "event", "event": event.to_dict()})
        return event

    async def new_context(self, channel_id: str) -> Event:
        self._ensure_member(channel_id)
        event = self.store.append_event(
            channel_id,
            "context_reset",
            "human",
            self.human_id,
            {},
        )
        self.bus.publish({"type": "event", "event": event.to_dict()})
        return event

    async def cancel_run(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        self._ensure_member(run.channel_id)
        self.cancelled.append(run_id)

    def partial_snapshots(self, channel_ids: set[str]) -> list[dict[str, Any]]:
        return [snapshot for snapshot in self.snapshots if snapshot.get("channel_id") in channel_ids]

    def queue_snapshots(self, channel_ids: set[str]) -> list[dict[str, Any]]:
        return []


class ThreadSafeStore(Store):
    """Test store shared with Starlette's test thread."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(str(path), isolation_level=None, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        schema = Path(__file__).parents[1] / "lgt" / "schema.sql"
        self.conn.executescript(schema.read_text(encoding="utf-8"))
        self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(kind, channel_id UNINDEXED, seq UNINDEXED, text)")
        self._savepoint_counter = 0


def _with_peer(app, peer: str = "127.0.0.1", *, normalize_ws_host: bool = True):
    async def asgi(scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            scope = dict(scope)
            scope["client"] = (peer, 45678)
            if scope["type"] == "websocket" and normalize_ws_host:
                scope["headers"] = [
                    (key, value) for key, value in scope["headers"] if key.lower() != b"host"
                ] + [(b"host", b"127.0.0.1")]
        await app(scope, receive, send)

    return asgi


@pytest.fixture
def gateway_client(tmp_path):
    orch = FakeOrchestrator(tmp_path)
    app = create_app(orch)
    with TestClient(_with_peer(app), base_url="http://127.0.0.1") as client:
        yield client, orch


def test_health_and_loopback_origin_policy(gateway_client):
    client, _ = gateway_client

    assert client.get("/health").json()["application"] == "lgt"
    same_origin = client.get("/health", headers={"origin": "http://127.0.0.1"})
    assert same_origin.status_code == 200
    cross_origin = client.get("/health", headers={"origin": "https://attacker.example"})
    assert cross_origin.status_code == 403
    assert cross_origin.json()["error"]["code"] == "local_only"
    cross_site_without_origin = client.get(
        "/health",
        headers={"sec-fetch-site": "cross-site"},
    )
    assert cross_site_without_origin.status_code == 403


def test_non_loopback_peer_is_rejected_even_without_origin(tmp_path):
    orch = FakeOrchestrator(tmp_path)
    app = create_app(orch, manage_lifespan=False)
    with TestClient(_with_peer(app, "8.8.8.8"), base_url="http://127.0.0.1") as client:
        response = client.get("/health")
    assert response.status_code == 403


def test_explicit_desktop_origin_cors_keeps_loopback_host_policy(tmp_path):
    orch = FakeOrchestrator(tmp_path)
    orch.settings.allowed_origins = ("tauri://localhost", "file://", "http://127.0.0.1:5173")
    app = create_app(orch, manage_lifespan=False)
    with TestClient(_with_peer(app), base_url="http://127.0.0.1") as client:
        response = client.get("/health", headers={"origin": "tauri://localhost"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "tauri://localhost"
        preflight = client.options("/health", headers={
            "origin": "http://127.0.0.1:5173",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        })
        assert preflight.status_code == 204
        assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        assert client.get("/health", headers={"origin": "http://127.0.0.1:5174"}).status_code == 403
        assert client.get("/health", headers={"origin": "null"}).status_code == 403
        assert client.get("/health", headers={"host": "attacker.example", "origin": "tauri://localhost"}).status_code == 403
        with client.websocket_connect("/ws", headers={"origin": "tauri://localhost"}) as socket:
            socket.send_json({"last_id": 0})
        with client.websocket_connect("/ws", headers={"origin": "http://127.0.0.1:5173"}) as socket:
            socket.send_json({"last_id": 0})
    orch.store.close()

    orch = FakeOrchestrator(tmp_path)
    orch.settings.allowed_origins = ("tauri://localhost",)
    with TestClient(_with_peer(create_app(orch, manage_lifespan=False), normalize_ws_host=False),
                    base_url="http://127.0.0.1") as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"host": "attacker.example",
                                                          "origin": "tauri://localhost"}):
                pass
    orch.store.close()


def test_agent_channel_member_and_event_routes(gateway_client):
    client, orch = gateway_client
    created = client.post("/channels", json={"name": "planning", "agent_ids": ["a1"]})
    assert created.status_code == 201
    channel = created.json()
    channel_id = channel["channel_id"]
    assert channel["name"] == "planning"
    assert channel_id in orch.bus.channel_updates[-1]

    channels = client.get("/channels").json()
    assert {item["name"] for item in channels} == {"general", "planning"}
    members = client.get(f"/channels/{channel_id}/members").json()
    assert {member["member_id"] for member in members} == {"local", "a1"}

    message_response = client.post(
        f"/channels/{channel_id}/messages",
        json={"text": "one", "mentions": []},
    )
    assert message_response.status_code == 201
    first = message_response.json()
    second = client.post(f"/channels/{channel_id}/messages", json={"text": "two"}).json()
    third = client.post(f"/channels/{channel_id}/messages", json={"text": "three"}).json()

    after_first = client.get(f"/channels/{channel_id}/events", params={"after_seq": first["seq"]})
    assert [event["seq"] for event in after_first.json()] == [2, 3]
    before_third = client.get(f"/channels/{channel_id}/events", params={"before_seq": third["seq"]})
    assert [event["seq"] for event in before_third.json()] == [1, 2]
    bounded = client.get(
        f"/channels/{channel_id}/events",
        params={"after_seq": first["seq"], "before_seq": third["seq"]},
    )
    assert [event["seq"] for event in bounded.json()] == [2]
    latest = client.get(f"/channels/{channel_id}/events", params={"limit": 2})
    assert [event["seq"] for event in latest.json()] == [2, 3]
    assert second["payload"]["text"] == "two"

    added = client.post(f"/channels/{channel_id}/members", json={"agent_id": "a1"})
    assert added.status_code == 201
    assert channel_id in orch.bus.channel_updates[-1]

    archived = client.post(f"/channels/{channel_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert orch.store.get_channel(channel_id).archived_at is not None


def test_strict_request_models_and_workspace_errors(gateway_client):
    client, orch = gateway_client
    channel_id = orch.store.list_channels(orch.human_id)[0].channel_id

    extra = client.post("/channels", json={"name": "bad", "unexpected": True})
    assert extra.status_code == 422
    empty_text = client.post(f"/channels/{channel_id}/messages", json={"text": ""})
    assert empty_text.status_code == 422
    missing = client.get("/channels/unknown/events")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    parent = orch.store.append_event(
        channel_id,
        "message",
        "human",
        orch.human_id,
        {"text": "parent", "mentions": []},
    )
    agent_event = orch.store.append_event(
        channel_id,
        "message",
        "agent",
        "a1",
        {"text": "agent text", "mentions": []},
        chain_id=parent.chain_id,
    )
    rejected = client.patch(
        f"/channels/{channel_id}/messages/{agent_event.seq}",
        json={"text": "cannot edit"},
    )
    assert rejected.status_code == 400

    conflict = client.post(f"/channels/{channel_id}/members", json={"agent_id": "missing-agent"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"


def test_run_routes_scope_cancel_and_return_workspace_objects(gateway_client):
    client, orch = gateway_client
    channel_id = orch.store.list_channels(orch.human_id)[0].channel_id
    run = Run(
        run_id="run-1",
        channel_id=channel_id,
        agent_id="a1",
        trigger_seq=1,
        delta_start_seq=1,
        delta_end_seq=1,
        session_mode="cold",
        harness="codex",
        cwd=".",
    )
    assert orch.store.create_run(run)

    channel_runs = client.get(f"/channels/{channel_id}/runs")
    assert channel_runs.status_code == 200
    assert [item["run_id"] for item in channel_runs.json()] == ["run-1"]
    assert client.get("/runs/run-1").json()["agent_id"] == "a1"
    cancelled = client.post("/runs/run-1/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["run_id"] == "run-1"
    assert orch.cancelled == ["run-1"]


def test_run_filter_log_and_catalog_routes(gateway_client, tmp_path):
    client, orch = gateway_client
    channel_id = orch.store.list_channels(orch.human_id)[0].channel_id
    run = Run(
        run_id="run-log", channel_id=channel_id, agent_id="a1", trigger_seq=1,
        delta_start_seq=1, delta_end_seq=1, session_mode="cold", harness="codex", cwd=".",
    )
    orch.store.create_run(run)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "run-log.stderr.log").write_text("first\nsecond\nthird\n", encoding="utf-8")
    orch.settings.log_dir = log_dir

    runs = client.get("/runs", params={"agent_id": "a1", "status": "active"})
    assert runs.status_code == 200
    assert [item["run_id"] for item in runs.json()] == ["run-log"]
    for number in (1, 2, 3):
        orch.store.create_run(Run(
            run_id=f"run-{number}", channel_id=channel_id, agent_id="a1",
            trigger_seq=number + 1, delta_start_seq=number + 1, delta_end_seq=number + 1,
            session_mode="cold", harness="codex", cwd=".",
            started_at=f"2026-10-08T00:00:0{number}+00:00",
        ))
    latest = client.get("/runs", params={"agent_id": "a1", "limit": 2}).json()
    assert [item["run_id"] for item in latest] == ["run-3", "run-2"]
    log = client.get("/runs/run-log/log", params={"tail": 2})
    assert log.json() == {"run_id": "run-log", "lines": ["second", "third"], "truncated": True}
    assert {item["name"] for item in client.get("/commands").json()} == {"/new", "/cwd", "/cancel"}


def test_attachment_thumbnail_is_bounded_and_scoped(gateway_client, tmp_path):
    from io import BytesIO
    import struct
    import zlib
    from PIL import Image
    from lgt.models import Attachment

    client, orch = gateway_client
    channel_id = orch.store.list_channels(orch.human_id)[0].channel_id
    source = tmp_path / "large.png"
    Image.new("RGB", (1200, 800), "red").save(source)
    orch.settings.thumbnail_max_dimension = 512
    orch.store.put_attachment(Attachment(
        attachment_id="thumb-one", channel_id=channel_id, filename="large.png",
        media_type="image/png", size_bytes=source.stat().st_size, sha256="test", path=str(source),
    ))
    response = client.get("/attachments/thumb-one/thumbnail")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(response.content)) as thumbnail:
        assert thumbnail.size == (512, 341)
    assert client.get("/attachments/missing/thumbnail").status_code == 404

    bomb = tmp_path / "spoofed.png"
    data = bytearray(source.read_bytes())
    data[16:24] = struct.pack(">II", 200_000, 200_000)
    data[29:33] = struct.pack(">I", zlib.crc32(b"IHDR" + data[16:29]))
    bomb.write_bytes(data)
    orch.store.put_attachment(Attachment(
        attachment_id="thumb-bomb", channel_id=channel_id, filename="spoofed.png",
        media_type="image/png", size_bytes=bomb.stat().st_size, sha256="test", path=str(bomb),
    ))
    assert client.get("/attachments/thumb-bomb/thumbnail").status_code == 413


def test_search_does_not_return_channels_outside_human_membership(gateway_client, tmp_path):
    client, orch = gateway_client
    own = orch.store.list_channels(orch.human_id)[0]
    outsider = Channel("outsider", "channel", "private keyword", str(tmp_path), False)
    orch.store.create_channel(outsider, [("agent", "a1")])
    orch.store.append_event(own.channel_id, "message", "human", "local", {"text": "keyword public"})
    orch.store.append_event(outsider.channel_id, "message", "human", "other", {"text": "keyword private"})
    results = client.get("/search", params={"q": "keyword"}).json()
    assert {item["channel_id"] for item in results["messages"]} == {own.channel_id}
    assert results["channels"] == []


def test_real_orchestrator_gateway_contracts(tmp_path):
    from lgt.orchestrator import Orchestrator
    from tests.support import ControlledFactory, FakeRouter, settings

    class Registry:
        prepared = []

        def list(self):
            return [{"harness": "codex", "found": True, "path": "codex", "version": "test",
                     "auth": "unknown", "capabilities": {"allowed_tools": False},
                     "models": [{"id": "test", "label": "Test", "description": "", "default": True}],
                     "tools": []}]

        async def scan(self):
            return self.list()

        async def probe_custom(self, command, extra_args):
            return {**self.list()[0], "harness": "custom", "command": command, "extra_args": extra_args}

        async def prepare_agent(self, agent):
            self.prepared.append(agent.agent_id)

        def validate_agent(self, agent):
            pass

    store = ThreadSafeStore(tmp_path / "real.sqlite3")
    orch = Orchestrator(store, settings(tmp_path), FakeRouter([]), ControlledFactory(),
                        lambda harness, sid, cwd: True, human_id="local",
                        harness_registry=Registry())
    with TestClient(_with_peer(create_app(orch)), base_url="http://127.0.0.1") as client:
        assert client.get("/harnesses").json()[0]["harness"] == "codex"
        assert client.post("/harnesses/custom/probe", json={"command": ["example"]}).json()["command"] == ["example"]
        probed = client.post("/harnesses/custom/probe", json={"command": ["example"], "extra_args": ["--profile", "local"]})
        assert probed.status_code == 200 and probed.json()["extra_args"] == ["--profile", "local"]
        assert [item["id"] for item in client.get("/templates").json()] == ["coder", "planner", "docs"]
        created = client.post("/agents", json={
            "handle": "helper", "name": "Helper", "description": "Tests the workspace",
            "harness": "codex", "model": "test", "system_prompt": "Help.",
        })
        assert created.status_code == 201
        agent = created.json()
        assert agent["avatar"]["seed"] == agent["agent_id"]
        assert agent["dm_channel_id"]
        assert agent["hue"] == 0
        assert agent["agent_id"] in orch.harness_registry.prepared
        assert client.get("/agents/status").json()[0]["state"] == "idle"
        channel_id = agent["dm_channel_id"]
        summary = next(item for item in client.get("/channels").json()
                       if item["channel_id"] == channel_id)
        assert summary["members"]
        assert summary["unread_count"] == 0
        assert client.get(f"/channels/{channel_id}/context").json()["agent_id"] == agent["agent_id"]
        assert client.post(f"/channels/{channel_id}/read", json={"seq": 0}).status_code == 200
        assert client.patch(f"/channels/{channel_id}", json={"name": "renamed"}).json()["name"] == "renamed"
        assert client.patch("/me", json={"display_name": "Tester"}).json()["display_name"] == "Tester"
        assert client.get("/me").json()["display_name"] == "Tester"
        assert client.get("/runs").json() == []
        assert client.get("/usage").json() == []
        normal = client.post("/channels", json={"name": "temporary", "cwd": str(tmp_path)}).json()
        pending = store.append_event(normal["channel_id"], "message", "human", "local",
                                     {"text": "pending", "mentions": []})
        queued = store.enqueue(normal["channel_id"], pending.seq, state="awaiting_route")
        archived = client.post(f"/channels/{normal['channel_id']}/archive")
        assert archived.status_code == 200 and archived.json()["archived_at"]
        assert store.get_queue_item(queued.queue_id).state == "cancelled"
        history = client.get(f"/channels/{normal['channel_id']}/events").json()
        assert history[-1]["kind"] == "channel_changed"
        assert client.post(f"/channels/{normal['channel_id']}/unarchive").json()["archived_at"] is None
        boot = client.post("/bootstrap", json={"agent_templates": ["coder"], "cwd": str(tmp_path)})
        assert boot.status_code == 201
        assert boot.json()["channel"]["name"] == "general"
        retired = client.post(f"/agents/{agent['agent_id']}/retire")
        assert retired.status_code == 200 and retired.json()["retired_at"]
        assert client.get("/channels").json()[0]
        assert client.post(f"/channels/{channel_id}/unarchive").status_code == 400
    store.close()


def test_http_agent_create_update_and_harness_rejection(gateway_client):
    client, orch = gateway_client
    assert client.get("/agents/a1").json()["handle"] == "builder"
    assert client.put("/agents/missing", json={
        "handle": "missing", "name": "Missing", "description": "",
        "harness": "codex", "model": "gpt-5-codex", "system_prompt": "",
    }).status_code == 404
    assert client.post("/agents", json={
        "agent_id": "a1", "handle": "another-handle", "name": "Duplicate",
        "description": "", "harness": "codex", "model": "gpt-5-codex",
        "system_prompt": "",
    }).status_code == 409
    payload = {
        "agent_id": "a2",
        "handle": "reviewer",
        "name": "Reviewer",
        "description": "Reviews code",
        "harness": "codex",
        "model": "gpt-5-codex",
        "system_prompt": "Review carefully.",
    }
    created = client.post("/agents", json=payload)
    assert created.status_code == 201
    assert created.json()["agent_id"] == "a2"

    replaced = client.put("/agents/a2", json={**payload, "agent_id": "a2", "name": "Updated"})
    assert replaced.status_code == 422  # PUT uses the path id and rejects extra body fields.
    replacement = {key: value for key, value in payload.items() if key != "agent_id"}
    replacement["name"] = "Updated"
    replaced = client.put("/agents/a2", json=replacement)
    assert replaced.status_code == 200
    assert replaced.json()["name"] == "Updated"

    unsupported = {**payload, "agent_id": "a3", "harness": "claude_code"}
    response = client.post("/agents", json=unsupported)
    assert response.status_code == 400
    assert "Codex" in response.json()["error"]["message"]


def test_websocket_replays_deduplicates_partial_snapshots_and_dispatches_commands(gateway_client):
    client, orch = gateway_client
    channel_id = orch.store.list_channels(orch.human_id)[0].channel_id
    event = orch.store.append_event(
        channel_id,
        "message",
        "human",
        orch.human_id,
        {"text": "before connect", "mentions": []},
    )
    orch.duplicate_during_replay = True
    orch.snapshots = [
        {"type": "snapshot", "id": "snapshot-1", "channel_id": channel_id, "text": "partial"},
        {"type": "snapshot", "id": "snapshot-1", "channel_id": channel_id, "text": "duplicate"},
    ]

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"last_id": 0})
        replay = websocket.receive_json()
        snapshot = websocket.receive_json()
        assert replay["type"] == "event"
        assert replay["event"]["id"] == event.id
        assert snapshot["text"] == "partial"

        websocket.send_json({"type": "unsupported"})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["error"]["code"] == "invalid_command"

        websocket.send_json({
            "type": "send_message",
            "channel_id": channel_id,
            "text": "after connect",
        })
        live = websocket.receive_json()
        assert live["type"] == "event"
        assert live["event"]["payload"]["text"] == "after connect"


def test_websocket_rejects_bad_cursor_and_cross_origin(tmp_path):
    orch = FakeOrchestrator(tmp_path)
    app = create_app(orch, manage_lifespan=False)
    with TestClient(_with_peer(app), base_url="http://127.0.0.1") as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"last_id": -1})
            bad_cursor = websocket.receive_json()
            assert bad_cursor["type"] == "error"
            assert bad_cursor["error"]["code"] == "invalid_cursor"

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws",
                headers={"origin": "https://attacker.example"},
            ):
                pass


def test_websocket_command_validation_and_context_dispatch(gateway_client):
    client, orch = gateway_client
    channel_id = orch.store.list_channels(orch.human_id)[0].channel_id

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"last_id": 0})
        websocket.send_json({"type": "new_context", "channel_id": channel_id, "extra": 1})
        malformed = websocket.receive_json()
        assert malformed["type"] == "error"
        assert malformed["error"]["code"] == "invalid_command"

        websocket.send_json({"type": "new_context", "channel_id": channel_id})
        event = websocket.receive_json()
        assert event["type"] == "event"
        assert event["event"]["kind"] == "context_reset"


def test_websocket_disconnect_does_not_cancel_an_accepted_message(gateway_client):
    client, orch = gateway_client
    channel_id = orch.store.list_channels(orch.human_id)[0].channel_id

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"last_id": 0})
        websocket.send_json({
            "type": "send_message",
            "channel_id": channel_id,
            "text": "accepted before disconnect",
        })
        accepted = websocket.receive_json()
        assert accepted["type"] == "event"
        assert accepted["event"]["payload"]["text"] == "accepted before disconnect"

    events = orch.store.events(channel_id)
    assert any(
        event.kind == "message" and event.payload.get("text") == "accepted before disconnect"
        for event in events
    )


def test_websocket_requests_resync_when_replay_exceeds_cap(gateway_client):
    client, orch = gateway_client
    channel_id = orch.store.list_channels(orch.human_id)[0].channel_id
    orch.settings.replay_cap = 2
    for index in range(3):
        orch.store.append_event(
            channel_id,
            "message",
            "human",
            orch.human_id,
            {"text": f"message {index}", "mentions": []},
        )

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"last_id": 0})
        resync = websocket.receive_json()
        assert resync == {"type": "resync", "channels": [channel_id]}


def test_lifespan_is_dependency_injected(gateway_client):
    _, orch = gateway_client
    assert orch.started is True
    assert orch.closed is False


def test_lifespan_starts_and_closes_injected_orchestrator(tmp_path):
    orch = FakeOrchestrator(tmp_path)
    app = create_app(orch)
    with TestClient(_with_peer(app), base_url="http://127.0.0.1") as client:
        assert client.get("/health").status_code == 200
        assert orch.started is True
        assert orch.closed is False
    assert orch.closed is True


def test_lifespan_can_be_disabled(tmp_path):
    orch = FakeOrchestrator(tmp_path)
    app = create_app(orch, manage_lifespan=False)
    with TestClient(_with_peer(app), base_url="http://127.0.0.1") as client:
        assert client.get("/health").status_code == 200
    assert orch.started is False
    assert orch.closed is False
    orch.store.close()
