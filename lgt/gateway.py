"""Local HTTP and WebSocket API for the multi-agent workspace."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import secrets
import sqlite3
from io import BytesIO
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lgt.attachments import VIEWABLE_IMAGE_TYPES, AttachmentTooLarge
from lgt.models import Agent, Attachment, Event, WorkspaceError, new_id
from lgt.services import COMMANDS, template_catalog
from lgt.run_errors import duration_ms, failure_text, normalize_error


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentCreate(_StrictModel):
    agent_id: str | None = Field(default=None, min_length=1)
    handle: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    harness: str = Field(min_length=1)
    model: str = Field(min_length=1)
    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    default_cwd: str | None = None
    permission_mode: str = "bypass"
    avatar: dict[str, str] | None = None
    extra_args: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)


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
    avatar: dict[str, str] | None = None
    extra_args: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)


class ReadBody(_StrictModel):
    seq: int = Field(ge=0)


class ChannelPatch(_StrictModel):
    name: str = Field(min_length=1)


class BootstrapBody(_StrictModel):
    agent_templates: list[str]
    cwd: str


class ProfilePatch(_StrictModel):
    display_name: str = Field(min_length=1, max_length=100)


class CustomProbeBody(_StrictModel):
    command: list[str] = Field(min_length=1)
    extra_args: list[str] = Field(default_factory=list)


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


def _scope_is_local_and_same_origin(scope: Mapping[str, Any], allowed_origins: tuple[str, ...] = ()) -> bool:
    client = scope.get("client")
    if not isinstance(client, (tuple, list)) or not client or not _loopback_host(str(client[0])):
        return False

    headers = {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }
    request_scheme = str(scope.get("scheme", "http"))
    normalized_request_scheme = {"ws": "http", "wss": "https"}.get(
        request_scheme, request_scheme,
    )
    request_authority = headers.get("host")
    if request_authority is None:
        server = scope.get("server")
        if not isinstance(server, (tuple, list)) or len(server) < 2:
            return False
        host, port = str(server[0]), int(server[1])
        request_authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    request_parts = _authority_parts(request_authority, normalized_request_scheme)
    if request_parts is None:
        return False

    origin = headers.get("origin")
    if origin is None:
        return headers.get("sec-fetch-site") not in {"cross-site", "same-site"}
    if origin in allowed_origins:
        return True

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

    if normalized_request_scheme != origin_scheme:
        return False
    origin_parts = _authority_parts(origin_authority, origin_scheme)
    return request_parts is not None and request_parts == origin_parts


def _event_payload(event: Any, store: Any = None) -> dict[str, Any]:
    if isinstance(event, Event):
        value = event.to_dict()
    elif isinstance(event, Mapping):
        value = dict(event)
    else:
        value = _plain(event)
    if store is not None and value.get("kind") == "run_status" and value.get("run_id"):
        payload = dict(value.get("payload", {}))
        if not {"agent_id", "started_at", "ended_at", "duration_ms"} <= payload.keys() or isinstance(payload.get("error"), str):
            run = store.get_run(value["run_id"])
            terminal = payload.get("status") in {"completed", "failed", "cancelled"}
            elapsed = run.duration_ms
            if elapsed is None and run.started_at and run.ended_at:
                elapsed = duration_ms(run.started_at, run.ended_at)
            payload.setdefault("agent_id", run.agent_id)
            payload.setdefault("started_at", run.started_at if payload.get("status") != "queued" else None)
            payload.setdefault("ended_at", run.ended_at if terminal else None)
            payload.setdefault("duration_ms", elapsed if terminal else None)
            if payload.get("error") or payload.get("status") == "failed":
                payload["error"] = normalize_error(payload.get("error") or run.error, run.exit_code)
                if payload.get("status") == "failed":
                    payload.setdefault("text", failure_text(run.harness, payload["error"], elapsed))
            value["payload"] = payload
    return value


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


def create_app(orch: Any, *, manage_lifespan: bool = True, daemon: Any = None) -> FastAPI:
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
        allowed = getattr(orch.settings, "allowed_origins", ())
        if not _scope_is_local_and_same_origin(request.scope, allowed):
            return _http_error(403, "local_only", "This workspace accepts approved local origins only.")
        origin = request.headers.get("origin")
        if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
            requested_method = request.headers["access-control-request-method"].upper()
            if requested_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                return _http_error(403, "forbidden", "The requested method is not allowed.")
            requested_headers = request.headers.get("access-control-request-headers", "")
            headers = {item.strip().lower() for item in requested_headers.split(",") if item.strip()}
            if not headers.issubset({"content-type", "authorization"}):
                return _http_error(403, "forbidden", "The requested headers are not allowed.")
            response = Response(status_code=204)
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        else:
            supplied = request.headers.get("authorization", "")
            if daemon is not None and not secrets.compare_digest(supplied.encode(), ("Bearer " + daemon.token).encode()):
                response = _http_error(401, "unauthorized", "A valid workspace token is required.")
            else:
                response = await call_next(request)
        if origin is not None:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

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
        return {"status": "ok", "application": "lgt", "api_version": 1, "pid": os.getpid()}

    @app.post("/shutdown")
    async def shutdown():
        if daemon is None:
            raise HTTPException(status_code=404, detail="Daemon mode is required.")
        daemon.request_shutdown()
        return {"status": "stopping"}

    @app.get("/harnesses")
    async def list_harnesses():
        return _plain(orch.harness_registry.list())

    @app.post("/harnesses/scan")
    async def scan_harnesses():
        return _plain(await orch.harness_registry.scan())

    @app.post("/harnesses/custom/probe")
    async def probe_custom_harness(body: CustomProbeBody):
        return _plain(await orch.harness_registry.probe_custom(body.command, body.extra_args))

    @app.get("/harnesses/{harness}/limits")
    async def harness_limits(harness: str):
        if harness not in {item["harness"] for item in orch.harness_registry.list()}:
            raise KeyError(harness)
        return _plain(orch.store.get_harness_limits(harness))

    @app.get("/templates")
    async def list_templates():
        return template_catalog(orch.harness_registry.list())

    @app.post("/bootstrap", status_code=201)
    async def bootstrap(body: BootstrapBody):
        result = await orch.bootstrap(body.agent_templates, body.cwd)
        _refresh_bus_channels(orch)
        return _plain(result)

    @app.get("/commands")
    async def list_commands():
        return COMMANDS

    @app.get("/me")
    async def get_profile():
        return _plain(orch.store.get_human_profile(orch.human_id))

    @app.patch("/me")
    async def patch_profile(body: ProfilePatch):
        return _plain(await orch.update_profile(body.display_name))

    @app.get("/agents")
    async def list_agents():
        return [_plain(agent) for agent in orch.store.list_agents()]

    @app.get("/agents/status")
    async def agent_statuses():
        return _plain(orch.agent_statuses())

    @app.get("/agents/{agent_id}")
    async def get_agent(agent_id: str):
        return _plain(orch.store.get_agent(agent_id))

    @app.post("/agents", status_code=201)
    async def create_agent(body: AgentCreate):
        data = body.model_dump()
        data["agent_id"] = data["agent_id"] or new_id()
        data["avatar"] = data["avatar"] or {}
        agent = Agent(**data)
        try:
            orch.store.get_agent(agent.agent_id)
        except KeyError:
            pass
        else:
            return _http_error(409, "conflict", "An agent with this id already exists.")
        if hasattr(orch, "harness_registry") and hasattr(orch.harness_registry, "prepare_agent"):
            await orch.harness_registry.prepare_agent(agent)
        orch.put_agent(agent)
        return _plain(orch.store.get_agent(agent.agent_id))

    @app.put("/agents/{agent_id}")
    async def replace_agent(agent_id: str, body: AgentReplace):
        current = orch.store.get_agent(agent_id)
        data = body.model_dump()
        if data["avatar"] is None:
            data["avatar"] = current.avatar
        agent = Agent(agent_id=agent_id, hue=current.hue, created_at=current.created_at,
                      dm_channel_id=current.dm_channel_id, retired_at=current.retired_at, **data)
        if hasattr(orch, "harness_registry") and hasattr(orch.harness_registry, "prepare_agent"):
            await orch.harness_registry.prepare_agent(agent)
        orch.put_agent(agent)
        return _plain(orch.store.get_agent(agent_id))

    @app.post("/agents/{agent_id}/retire")
    @app.delete("/agents/{agent_id}")
    async def retire_agent(agent_id: str):
        return _plain(await orch.retire_agent(agent_id))

    @app.get("/channels")
    async def list_channels():
        return _plain(orch.store.list_channel_summaries(orch.human_id))

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

    @app.patch("/channels/{channel_id}")
    async def patch_channel(channel_id: str, body: ChannelPatch):
        _require_channel(orch, channel_id)
        return _plain(await orch.patch_channel(channel_id, name=body.name))

    @app.post("/channels/{channel_id}/unarchive")
    async def unarchive_channel(channel_id: str):
        _require_channel(orch, channel_id)
        return _plain(await orch.unarchive_channel(channel_id))

    @app.post("/channels/{channel_id}/read")
    async def mark_read(channel_id: str, body: ReadBody):
        _require_channel(orch, channel_id)
        return _plain(await orch.mark_read(channel_id, body.seq))

    @app.get("/channels/{channel_id}/context")
    async def context_stats(channel_id: str, agent_id: str | None = None):
        _require_channel(orch, channel_id)
        return _plain(orch.context_stats(channel_id, agent_id))

    @app.get("/channels/{channel_id}/suggestions")
    async def channel_suggestions(channel_id: str):
        _require_channel(orch, channel_id)
        return _plain(await orch.channel_suggestions(channel_id))

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

    @app.get("/attachments/{attachment_id}/thumbnail")
    async def thumbnail(attachment_id: str):
        attachment = orch.store.get_attachment(attachment_id)
        _require_channel(orch, attachment.channel_id)
        if attachment.media_type not in VIEWABLE_IMAGE_TYPES:
            return _http_error(415, "unsupported_media_type", "Thumbnails require an image attachment.")
        from PIL import Image, UnidentifiedImageError

        def render() -> bytes:
            with Image.open(attachment.path) as source:
                if source.width * source.height > 40_000_000:
                    raise AttachmentTooLarge("image dimensions exceed the thumbnail limit")
                source.thumbnail((orch.settings.thumbnail_max_dimension,) * 2)
                output = BytesIO()
                source.convert("RGB").save(output, format="JPEG", quality=82)
                return output.getvalue()

        try:
            data = await anyio.to_thread.run_sync(render)
        except Image.DecompressionBombError:
            return _http_error(413, "too_large", "image dimensions exceed the thumbnail limit")
        except (UnidentifiedImageError, OSError):
            return _http_error(415, "invalid_image", "The attachment is not a readable image.")
        return Response(data, media_type="image/jpeg", headers={"X-Content-Type-Options": "nosniff"})

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
        return [_event_payload(event, orch.store) for event in events]

    @app.get("/channels/{channel_id}/runs")
    async def list_runs(channel_id: str):
        _require_channel(orch, channel_id)
        return [_plain(run) for run in orch.store.list_runs(channel_id)]

    @app.get("/runs")
    async def list_all_runs(
        agent_id: str | None = None,
        channel_id: str | None = None,
        status: Literal["active", "terminal"] | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        if channel_id is not None:
            _require_channel(orch, channel_id)
        visible = _channel_ids_for_human(orch)
        queried_channels = [channel_id] if channel_id is not None else sorted(visible)
        runs = [run for cid in queried_channels for run in orch.store.list_runs(
            cid, agent_id=agent_id, status=status, limit=limit, newest_first=True,
        )]
        runs.sort(key=lambda run: (run.started_at or "", run.run_id), reverse=True)
        return [_plain(run) for run in runs[:limit]]

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        run = orch.store.get_run(run_id)
        _require_channel(orch, run.channel_id)
        return _plain(run)

    @app.get("/runs/{run_id}/log")
    async def run_log(run_id: str, tail: int = Query(default=200, ge=1, le=10000)):
        run = orch.store.get_run(run_id)
        _require_channel(orch, run.channel_id)
        # A run id must never contribute path components to the log filename.
        if not run_id.isascii() or not all(char.isalnum() or char in "-_" for char in run_id):
            raise KeyError(run_id)
        path = Path(orch.settings.log_dir) / f"{run_id}.stderr.log"
        if not path.is_file():
            return {"run_id": run_id, "lines": [], "truncated": False}

        def read_tail() -> tuple[list[str], bool]:
            from collections import deque

            with path.open("r", encoding="utf-8", errors="replace") as stream:
                lines = deque(stream, maxlen=tail + 1)
            return [line.rstrip("\r\n") for line in list(lines)[-tail:]], len(lines) > tail

        lines, truncated = await anyio.to_thread.run_sync(read_tail)
        return {"run_id": run_id, "lines": lines, "truncated": truncated}

    @app.get("/usage")
    async def usage(group_by: Literal["agent", "channel", "day"] = "agent", since: str | None = None):
        return _plain(orch.store.usage(group_by=group_by, since=since))

    @app.get("/search")
    async def search(q: str = Query(min_length=1), channel_id: str | None = None,
                     kinds: str | None = None):
        if channel_id is not None:
            _require_channel(orch, channel_id)
        found = orch.store.search(q, channel_id=channel_id,
                                  kinds=kinds.split(",") if kinds else None)
        visible = _channel_ids_for_human(orch)
        return {**found,
                "channels": [item for item in found["channels"] if item["channel_id"] in visible],
                "messages": [item for item in found["messages"] if item["channel_id"] in visible]}

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
        return _event_payload(event, orch.store)

    @app.post("/channels/{channel_id}/messages/{seq}/cancel")
    async def cancel_delivery(channel_id: str, seq: int, body: CancelDeliveryBody | None = None):
        _require_channel(orch, channel_id)
        event = await orch.cancel_delivery(channel_id, seq, body.agent_ids if body else None)
        return _event_payload(event, orch.store)

    @app.patch("/channels/{channel_id}/messages/{seq}")
    async def edit_message(channel_id: str, seq: int, body: EditMessageBody):
        _require_channel(orch, channel_id)
        event = await orch.edit_message(channel_id, seq, body.text, body.deleted)
        return _event_payload(event, orch.store)

    @app.post("/channels/{channel_id}/new")
    async def new_context(channel_id: str):
        _require_channel(orch, channel_id)
        event = await orch.new_context(channel_id)
        return _event_payload(event, orch.store)

    @app.post("/channels/{channel_id}/archive")
    async def archive_channel(channel_id: str):
        _require_channel(orch, channel_id)
        if hasattr(orch, "patch_channel"):
            channel = await orch.patch_channel(channel_id, archived=True)
        else:
            orch.store.archive_channel(channel_id)
            channel = orch.store.get_channel(channel_id)
        _refresh_bus_channels(orch)
        return _plain(channel)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        if not _scope_is_local_and_same_origin(
            websocket.scope, getattr(orch.settings, "allowed_origins", ()),
        ):
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
                initial = await asyncio.wait_for(websocket.receive_json(), timeout=5) if daemon is not None else await websocket.receive_json()
                if daemon is not None:
                    supplied_token = initial.get("token") if isinstance(initial, dict) else None
                    if not isinstance(supplied_token, str) or not secrets.compare_digest(supplied_token.encode(), daemon.token.encode()):
                        await websocket.close(code=1008, reason="A valid workspace token is required.")
                        return
                    initial = dict(initial)
                    initial.pop("token")
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
            except TimeoutError:
                await websocket.close(code=1008, reason="Workspace authentication timed out.")
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
            state_frames = orch.snapshot_frames(channel_ids) if hasattr(orch, "snapshot_frames") else []
            replay_max = max([last_id, *(event.id for event in replay)])
            if len(replay) > replay_cap:
                await websocket.send_json({"type": "resync", "channels": sorted(channel_ids)})
            else:
                for event in replay:
                    await websocket.send_json({"type": "event", "event": _event_payload(event, orch.store)})

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
            for frame in state_frames:
                await websocket.send_json(_plain(frame))

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
