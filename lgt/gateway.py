"""Local HTTP and WebSocket API for the multi-agent workspace."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import sqlite3
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lgt.attachments import VIEWABLE_IMAGE_TYPES, AttachmentTooLarge
from lgt.models import Agent, Attachment, Event, WorkspaceError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentCreate(_StrictModel):
    agent_id: str = Field(min_length=1)
    handle: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    harness: str = Field(min_length=1)
    model: str = Field(min_length=1)
    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    default_cwd: str | None = None
    permission_mode: str = "bypass"


class AgentReplace(_StrictModel):
    handle: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    harness: str = Field(min_length=1)
    model: str = Field(min_length=1)
    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    default_cwd: str | None = None
    permission_mode: str = "bypass"


class ChannelCreate(_StrictModel):
    name: str = Field(min_length=1)
    kind: Literal["channel", "dm"] = "channel"
    agent_ids: list[str] | None = None
    cwd: str | None = None


class MemberCreate(_StrictModel):
    agent_id: str = Field(min_length=1)


def _require_content(text: str, attachments: list[str] | None) -> None:
    if not text.strip() and not attachments:
        raise ValueError("provide text or attachments")


class SendMessageBody(_StrictModel):
    text: str = ""
    mentions: list[str] | None = None
    attachments: list[str] | None = None

    @model_validator(mode="after")
    def require_content(self) -> SendMessageBody:
        _require_content(self.text, self.attachments)
        return self


class ChannelCwdBody(_StrictModel):
    cwd: str | None = Field(description="An existing absolute directory, or null for a managed one.")


class CancelDeliveryBody(_StrictModel):
    agent_ids: list[str] | None = None


class EditMessageBody(_StrictModel):
    text: str | None = None
    deleted: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> EditMessageBody:
        if self.text is None and self.deleted is None:
            raise ValueError("provide text or deleted")
        return self


class _WSSendMessage(_StrictModel):
    type: Literal["send_message"]
    channel_id: str = Field(min_length=1)
    text: str = ""
    mentions: list[str] | None = None
    attachments: list[str] | None = None

    @model_validator(mode="after")
    def require_content(self) -> _WSSendMessage:
        _require_content(self.text, self.attachments)
        return self


class _WSEditMessage(_StrictModel):
    type: Literal["edit_message"]
    channel_id: str = Field(min_length=1)
    target_seq: int = Field(gt=0)
    text: str | None = None
    deleted: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> _WSEditMessage:
        if self.text is None and self.deleted is None:
            raise ValueError("provide text or deleted")
        return self


class _WSCancelRun(_StrictModel):
    type: Literal["cancel_run"]
    run_id: str = Field(min_length=1)


class _WSNewContext(_StrictModel):
    type: Literal["new_context"]
    channel_id: str = Field(min_length=1)


class _WSCancelDelivery(_StrictModel):
    type: Literal["cancel_delivery"]
    channel_id: str = Field(min_length=1)
    target_seq: int = Field(gt=0)
    agent_ids: list[str] | None = None


_WS_COMMAND_MODELS: dict[str, type[BaseModel]] = {
    "send_message": _WSSendMessage,
    "edit_message": _WSEditMessage,
    "cancel_run": _WSCancelRun,
    "new_context": _WSNewContext,
    "cancel_delivery": _WSCancelDelivery,
}


def _plain(value: Any) -> Any:
    if isinstance(value, Event):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    return jsonable_encoder(value)


def _attachment_payload(attachment: Attachment) -> dict[str, Any]:
    return {
        **attachment.summary(),
        "channel_id": attachment.channel_id,
        "sha256": attachment.sha256,
        "message_seq": attachment.message_seq,
        "created_at": attachment.created_at,
        "url": f"/attachments/{attachment.attachment_id}",
    }


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _loopback_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip().lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]").split("%", 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            return address.ipv4_mapped.is_loopback
        return address.is_loopback
    except ValueError:
        return False


def _authority_parts(authority: str, scheme: str) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(f"{scheme}://{authority}")
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not _loopback_host(host):
        return None
    normalized_scheme = {"ws": "http", "wss": "https"}.get(scheme, scheme)
    default_port = 443 if normalized_scheme == "https" else 80
    return host.lower().rstrip("."), port or default_port


def _scope_is_local_and_same_origin(scope: Mapping[str, Any]) -> bool:
    client = scope.get("client")
    if not isinstance(client, (tuple, list)) or not client or not _loopback_host(str(client[0])):
        return False

    headers = {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }
    origin = headers.get("origin")
    if origin is None:
        return headers.get("sec-fetch-site") not in {"cross-site", "same-site"}

    try:
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.query
            or parsed_origin.fragment
            or parsed_origin.username is not None
            or parsed_origin.password is not None
            or parsed_origin.hostname is None
        ):
            return False
        origin_scheme = parsed_origin.scheme
        origin_authority = parsed_origin.netloc
    except ValueError:
        return False

    request_scheme = str(scope.get("scheme", "http"))
    normalized_request_scheme = {"ws": "http", "wss": "https"}.get(
        request_scheme, request_scheme,
    )
    if normalized_request_scheme != origin_scheme:
        return False

    request_authority = headers.get("host")
    if request_authority is None:
        server = scope.get("server")
        if not isinstance(server, (tuple, list)) or len(server) < 2:
            return False
        host, port = str(server[0]), int(server[1])
        request_authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"

    request_parts = _authority_parts(request_authority, normalized_request_scheme)
    origin_parts = _authority_parts(origin_authority, origin_scheme)
    return request_parts is not None and request_parts == origin_parts


def _event_payload(event: Any) -> dict[str, Any]:
    if isinstance(event, Event):
        return event.to_dict()
    if isinstance(event, Mapping):
        return dict(event)
    return _plain(event)


def _event_id(message: Any) -> int | None:
    if not isinstance(message, Mapping) or message.get("type") != "event":
        return None
    event = message.get("event")
    if isinstance(event, Event):
        return event.id
    if isinstance(event, Mapping):
        event_id = event.get("id")
        return event_id if type(event_id) is int else None
    return None


def _snapshot_identifier(snapshot: Mapping[str, Any]) -> Any:
    return snapshot.get("id", snapshot.get("run_id"))


def _channel_ids_for_human(orch: Any) -> set[str]:
    return {
        channel.channel_id
        for channel in orch.store.list_channels(orch.human_id)
    }


def _refresh_bus_channels(orch: Any) -> None:
    orch.bus.update_channels(_channel_ids_for_human(orch))


def _require_channel(orch: Any, channel_id: str) -> Any:
    channel = orch.store.get_channel(channel_id)
    if not any(
        member.get("member_kind") == "human"
        and member.get("member_id") == orch.human_id
        for member in orch.store.members(channel_id)
    ):
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


def _http_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=_error(code, message))


def _command_error(error: BaseException) -> dict[str, Any]:
    if isinstance(error, KeyError):
        return _error("not_found", "The requested workspace item was not found.")
    if isinstance(error, sqlite3.IntegrityError):
        return _error("conflict", "The workspace change conflicts with existing data.")
    if isinstance(error, (WorkspaceError, ValueError)):
        return _error("invalid_command", str(error))
    if isinstance(error, HTTPException):
        return _error("not_found" if error.status_code == 404 else "forbidden", str(error.detail))
    return _error("internal_error", "The workspace command failed.")


def create_app(orch: Any, *, manage_lifespan: bool = True) -> FastAPI:
    """Create the local API around an injected, already configured orchestrator."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if manage_lifespan:
            await orch.start()
        try:
            yield
        finally:
            if manage_lifespan:
                await orch.close()

    app = FastAPI(lifespan=lifespan)
    app.state.orchestrator = orch

    @app.middleware("http")
    async def require_loopback_origin(request: Request, call_next):
        if not _scope_is_local_and_same_origin(request.scope):
            return _http_error(403, "local_only", "This workspace accepts local same-origin requests only.")
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def handle_not_found(_: Request, error: KeyError):
        return _http_error(404, "not_found", "The requested workspace item was not found.")

    @app.exception_handler(sqlite3.IntegrityError)
    async def handle_conflict(_: Request, error: sqlite3.IntegrityError):
        return _http_error(409, "conflict", "The workspace change conflicts with existing data.")

    @app.exception_handler(AttachmentTooLarge)
    async def handle_too_large(_: Request, error: AttachmentTooLarge):
        return _http_error(413, "too_large", str(error))

    @app.exception_handler(WorkspaceError)
    async def handle_workspace_error(_: Request, error: WorkspaceError):
        return _http_error(400, "invalid_request", str(error))

    @app.exception_handler(ValueError)
    async def handle_value_error(_: Request, error: ValueError):
        return _http_error(400, "invalid_request", str(error))

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/agents")
    async def list_agents():
        return [_plain(agent) for agent in orch.store.list_agents()]

    @app.get("/agents/{agent_id}")
    async def get_agent(agent_id: str):
        return _plain(orch.store.get_agent(agent_id))

    @app.post("/agents", status_code=201)
    async def create_agent(body: AgentCreate):
        agent = Agent(**body.model_dump())
        try:
            orch.store.get_agent(agent.agent_id)
        except KeyError:
            pass
        else:
            return _http_error(409, "conflict", "An agent with this id already exists.")
        orch.put_agent(agent)
        return _plain(orch.store.get_agent(agent.agent_id))

    @app.put("/agents/{agent_id}")
    async def replace_agent(agent_id: str, body: AgentReplace):
        orch.store.get_agent(agent_id)
        agent = Agent(agent_id=agent_id, **body.model_dump())
        orch.put_agent(agent)
        return _plain(orch.store.get_agent(agent_id))

    @app.get("/channels")
    async def list_channels():
        return [_plain(channel) for channel in orch.store.list_channels(orch.human_id)]

    @app.post("/channels", status_code=201)
    async def create_channel(body: ChannelCreate):
        channel = orch.create_channel(
            body.name,
            body.kind,
            body.agent_ids,
            body.cwd,
        )
        _refresh_bus_channels(orch)
        return _plain(channel)

    @app.get("/channels/{channel_id}/members")
    async def list_members(channel_id: str):
        _require_channel(orch, channel_id)
        return orch.store.members(channel_id)

    @app.post("/channels/{channel_id}/members", status_code=201)
    async def add_member(channel_id: str, body: MemberCreate):
        _require_channel(orch, channel_id)
        orch.add_member(channel_id, body.agent_id)
        _refresh_bus_channels(orch)
        return orch.store.members(channel_id)

    @app.delete("/channels/{channel_id}/members/{agent_id}")
    async def remove_member(channel_id: str, agent_id: str):
        _require_channel(orch, channel_id)
        await orch.remove_member(channel_id, agent_id)
        return orch.store.members(channel_id)

    @app.put("/channels/{channel_id}/cwd")
    async def set_channel_cwd(channel_id: str, body: ChannelCwdBody):
        _require_channel(orch, channel_id)
        return _plain(await orch.set_channel_cwd(channel_id, body.cwd))

    @app.get("/channels/{channel_id}/queue")
    async def list_queue(channel_id: str):
        _require_channel(orch, channel_id)
        return orch.queue_items(channel_id)

    @app.post("/channels/{channel_id}/attachments", status_code=201)
    async def upload_attachment(
        channel_id: str,
        request: Request,
        filename: str = Query(min_length=1, max_length=255),
    ):
        """Upload one file as the raw request body; Content-Type is its media type."""
        _require_channel(orch, channel_id)
        declared = request.headers.get("content-length", "")
        limit = orch.settings.attachment_max_bytes
        if declared.isdigit() and int(declared) > limit:
            return _http_error(413, "too_large", f"attachment exceeds the {limit}-byte limit")
        attachment = await orch.create_attachment(
            channel_id, filename, request.headers.get("content-type"), request.stream(),
        )
        return _attachment_payload(attachment)

    @app.get("/attachments/{attachment_id}")
    async def download_attachment(attachment_id: str):
        attachment = orch.store.get_attachment(attachment_id)
        _require_channel(orch, attachment.channel_id)
        # Uploaded HTML or SVG must never run in the workspace origin.
        inline = attachment.media_type in VIEWABLE_IMAGE_TYPES
        return FileResponse(
            attachment.path,
            media_type=attachment.media_type if inline else "application/octet-stream",
            filename=attachment.filename,
            content_disposition_type="inline" if inline else "attachment",
            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
        )

    @app.get("/attachments/{attachment_id}/meta")
    async def attachment_metadata(attachment_id: str):
        attachment = orch.store.get_attachment(attachment_id)
        _require_channel(orch, attachment.channel_id)
        return _attachment_payload(attachment)

    @app.delete("/attachments/{attachment_id}", status_code=204)
    async def delete_attachment(attachment_id: str):
        attachment = orch.store.get_attachment(attachment_id)
        _require_channel(orch, attachment.channel_id)
        orch.delete_attachment(attachment_id)

    @app.get("/channels/{channel_id}/events")
    async def list_events(
        channel_id: str,
        before_seq: int | None = Query(default=None, ge=0),
        after_seq: int | None = Query(default=None, ge=0),
        limit: int = Query(default=100, gt=0),
    ):
        _require_channel(orch, channel_id)
        events = orch.store.scrollback(
            channel_id,
            before_seq=before_seq,
            after_seq=after_seq,
            limit=limit,
        )
        return [_event_payload(event) for event in events]

    @app.get("/channels/{channel_id}/runs")
    async def list_runs(channel_id: str):
        _require_channel(orch, channel_id)
        return [_plain(run) for run in orch.store.list_runs(channel_id)]

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        run = orch.store.get_run(run_id)
        _require_channel(orch, run.channel_id)
        return _plain(run)

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        run = orch.store.get_run(run_id)
        _require_channel(orch, run.channel_id)
        await orch.cancel_run(run_id)
        return {"status": "cancel_requested", "run_id": run_id}

    @app.post("/channels/{channel_id}/messages", status_code=201)
    async def send_message(channel_id: str, body: SendMessageBody):
        _require_channel(orch, channel_id)
        event = await orch.send_message(channel_id, body.text, body.mentions, body.attachments)
        return _event_payload(event)

    @app.post("/channels/{channel_id}/messages/{seq}/cancel")
    async def cancel_delivery(channel_id: str, seq: int, body: CancelDeliveryBody | None = None):
        _require_channel(orch, channel_id)
        event = await orch.cancel_delivery(channel_id, seq, body.agent_ids if body else None)
        return _event_payload(event)

    @app.patch("/channels/{channel_id}/messages/{seq}")
    async def edit_message(channel_id: str, seq: int, body: EditMessageBody):
        _require_channel(orch, channel_id)
        event = await orch.edit_message(channel_id, seq, body.text, body.deleted)
        return _event_payload(event)

    @app.post("/channels/{channel_id}/new")
    async def new_context(channel_id: str):
        _require_channel(orch, channel_id)
        event = await orch.new_context(channel_id)
        return _event_payload(event)

    @app.post("/channels/{channel_id}/archive")
    async def archive_channel(channel_id: str):
        _require_channel(orch, channel_id)
        orch.store.archive_channel(channel_id)
        _refresh_bus_channels(orch)
        return _plain(orch.store.get_channel(channel_id))

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        if not _scope_is_local_and_same_origin(websocket.scope):
            await websocket.close(code=1008, reason="local same-origin access required")
            return
        await websocket.accept()
        subscription = None
        command_tasks: set[asyncio.Task[None]] = set()
        receive_task: asyncio.Task[Any] | None = None
        event_task: asyncio.Task[Any] | None = None
        error_task: asyncio.Task[Any] | None = None
        try:
            try:
                initial = await websocket.receive_json()
                if (
                    not isinstance(initial, dict)
                    or set(initial) != {"last_id"}
                    or type(initial.get("last_id")) is not int
                    or initial["last_id"] < 0
                ):
                    await websocket.send_json({
                        "type": "error",
                        "error": {"code": "invalid_cursor", "message": "First frame must contain a nonnegative integer last_id."},
                    })
                    await websocket.close(code=1008)
                    return
            except (ValueError, WebSocketDisconnect):
                await websocket.send_json({
                    "type": "error",
                    "error": {"code": "invalid_cursor", "message": "First frame must contain a nonnegative integer last_id."},
                })
                await websocket.close(code=1008)
                return

            last_id = initial["last_id"]
            channel_ids = _channel_ids_for_human(orch)
            replay_cap = orch.settings.replay_cap
            subscription = orch.bus.subscribe(channel_ids, capacity=replay_cap)
            replay = orch.store.replay(last_id, sorted(channel_ids), replay_cap + 1)
            snapshots = orch.partial_snapshots(channel_ids)
            queues = orch.queue_snapshots(channel_ids)
            replay_max = max([last_id, *(event.id for event in replay)])
            if len(replay) > replay_cap:
                await websocket.send_json({"type": "resync", "channels": sorted(channel_ids)})
            else:
                for event in replay:
                    await websocket.send_json({"type": "event", "event": _event_payload(event)})

            seen_snapshots: set[Any] = set()
            for snapshot in snapshots:
                snapshot_id = _snapshot_identifier(snapshot)
                if snapshot_id is not None:
                    try:
                        if snapshot_id in seen_snapshots:
                            continue
                        seen_snapshots.add(snapshot_id)
                    except TypeError:
                        pass
                await websocket.send_json(_plain(snapshot))
            for queue in queues:
                await websocket.send_json(queue)

            command_errors: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def run_command(raw: Any) -> None:
                try:
                    await _dispatch_ws_command(orch, raw)
                except BaseException as error:
                    if isinstance(error, asyncio.CancelledError):
                        raise
                    await command_errors.put({"type": "error", **_command_error(error)})

            def command_done(task: asyncio.Task[None]) -> None:
                command_tasks.discard(task)

            receive_task = asyncio.create_task(websocket.receive())
            event_task = asyncio.create_task(subscription.queue.get())
            error_task = asyncio.create_task(command_errors.get())
            while True:
                done, _ = await asyncio.wait(
                    {receive_task, event_task, error_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receive_task in done:
                    try:
                        incoming = receive_task.result()
                    except WebSocketDisconnect:
                        return
                    if incoming.get("type") == "websocket.disconnect":
                        return
                    if incoming.get("type") != "websocket.receive":
                        await websocket.send_json({
                            "type": "error",
                            "error": {"code": "invalid_command", "message": "Expected a JSON command object."},
                        })
                    else:
                        raw_text = incoming.get("text")
                        try:
                            raw = json.loads(raw_text) if isinstance(raw_text, str) else incoming.get("bytes")
                            if isinstance(raw, bytes):
                                raw = json.loads(raw.decode("utf-8"))
                        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                            raw = None
                        if raw is None:
                            await websocket.send_json({
                                "type": "error",
                                "error": {"code": "invalid_command", "message": "Command frame must contain valid JSON."},
                            })
                        else:
                            task = asyncio.create_task(run_command(raw))
                            command_tasks.add(task)
                            task.add_done_callback(command_done)
                    receive_task = asyncio.create_task(websocket.receive())

                if error_task in done:
                    await websocket.send_json(error_task.result())
                    error_task = asyncio.create_task(command_errors.get())

                if event_task in done:
                    message = event_task.result()
                    durable_id = _event_id(message)
                    if durable_id is None or durable_id > replay_max:
                        if durable_id is not None:
                            replay_max = max(replay_max, durable_id)
                        await websocket.send_json(_plain(message))
                    if isinstance(message, Mapping) and message.get("type") == "resync":
                        await websocket.close(code=1013, reason="event queue overflow; resync required")
                        return
                    event_task = asyncio.create_task(subscription.queue.get())
        except WebSocketDisconnect:
            return
        finally:
            # Starlette's WebSocket test client (and server shutdown) cancels
            # the connection task immediately after sending disconnect. Finish
            # local cleanup, and let already accepted workspace commands reach
            # their durable mailbox operation, before honoring that cancellation.
            with anyio.CancelScope(shield=True):
                if subscription is not None:
                    orch.bus.unsubscribe(subscription)
                transient_tasks = tuple(
                    task for task in (receive_task, event_task, error_task)
                    if task is not None
                )
                for task in transient_tasks:
                    if not task.done():
                        task.cancel()
                if transient_tasks:
                    await asyncio.gather(*transient_tasks, return_exceptions=True)
                accepted_commands = tuple(command_tasks)
                if accepted_commands:
                    await asyncio.gather(*accepted_commands, return_exceptions=True)

    return app


async def _dispatch_ws_command(orch: Any, raw: Any) -> None:
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
        raise ValueError("Command must be an object with a string type.")
    command_model = _WS_COMMAND_MODELS.get(raw["type"])
    if command_model is None:
        raise ValueError("Unknown command type.")
    try:
        command = command_model.model_validate(raw)
    except ValidationError:
        raise ValueError("Command fields are invalid or incomplete.") from None

    if isinstance(command, _WSSendMessage):
        await orch.send_message(command.channel_id, command.text, command.mentions, command.attachments)
    elif isinstance(command, _WSEditMessage):
        await orch.edit_message(
            command.channel_id,
            command.target_seq,
            command.text,
            command.deleted,
        )
    elif isinstance(command, _WSCancelRun):
        await orch.cancel_run(command.run_id)
    elif isinstance(command, _WSNewContext):
        await orch.new_context(command.channel_id)
    elif isinstance(command, _WSCancelDelivery):
        await orch.cancel_delivery(command.channel_id, command.target_seq, command.agent_ids)
