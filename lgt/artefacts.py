"""Channel-scoped, filesystem-backed artefacts. No database catalogue."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from .models import Channel, WorkspaceError

TYPES = {".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html", ".pdf": "pdf"}
MAX_BYTES = 32 * 1024 * 1024


def root(channel: Channel, *, setup: bool = False) -> Path:
    cwd = Path(channel.cwd).resolve()
    directory = cwd
    for part in (".lgt", "artefacts", channel.channel_id):
        if not part or Path(part).name != part or part in {".", ".."}:
            raise WorkspaceError("Invalid artefact directory")
        directory = directory / part
        if directory.is_symlink():
            raise WorkspaceError("Artefact directories cannot be symbolic links")
        if setup:
            directory.mkdir(exist_ok=True, parents=True)
    return directory


def path_for(channel: Channel, name: str, *, existing: bool = True) -> Path:
    directory = root(channel)
    relative = Path(name)
    if (not name or relative.is_absolute() or ".." in relative.parts or "\\" in name
            or ":" in name or any(ord(char) < 32 for char in name)
            or relative.suffix.lower() not in TYPES):
        raise WorkspaceError("Choose a Markdown, HTML or PDF file inside this channel's artefact folder")
    path = directory
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise WorkspaceError("Symbolic links are not artefacts")
    if not path.resolve().is_relative_to(directory.resolve()):
        raise WorkspaceError("Artefact is outside this channel's folder")
    if existing and not path.is_file():
        raise KeyError(name)
    return path


def describe(channel: Channel, name: str) -> dict[str, Any]:
    path = path_for(channel, name)
    stat = path.stat()
    return {"name": path.name, "path": name, "kind": TYPES[path.suffix.lower()],
            "size_bytes": stat.st_size, "revision": f"{stat.st_mtime_ns}-{stat.st_size}"}


def listing(channel: Channel) -> list[dict[str, Any]]:
    directory = root(channel)
    result = []
    for parent, dirs, files in os.walk(directory, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
        for filename in files:
            path = Path(parent) / filename
            if path.suffix.lower() not in TYPES or path.is_symlink():
                continue
            try:
                result.append(describe(channel, path.relative_to(directory).as_posix()))
            except (OSError, KeyError, WorkspaceError):
                continue  # An external edit may race the directory scan.
    return sorted(result, key=lambda item: item["path"].casefold())


def read(channel: Channel, name: str) -> tuple[dict[str, Any], bytes]:
    metadata = describe(channel, name)
    with path_for(channel, name).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise WorkspaceError("Artefact exceeds the 32 MiB preview limit")
    return metadata, data


def announcement(text: str) -> dict[str, str] | None:
    # A complete control message only; examples embedded in prose cannot activate it.
    match = re.fullmatch(r"\s*```lgt-artefact\s*\n(.*?)\n```\s*", text, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match[1])
    except ValueError as error:
        raise WorkspaceError("Invalid lgt-artefact JSON") from error
    if (not isinstance(value, dict) or set(value) != {"name", "path"}
            or any(not isinstance(value[k], str) or not value[k].strip() for k in value)):
        raise WorkspaceError("Artefact announcement requires name and path")
    return value


def announced_file(channel: Channel, value: dict[str, str]) -> dict[str, Any]:
    directory = root(channel)
    candidate = Path(value["path"])
    if candidate.is_absolute():
        try:
            name = candidate.relative_to(directory).as_posix()
        except ValueError as error:
            raise WorkspaceError("Save the artefact inside this channel's artefact folder") from error
    else:
        name = value["path"]
    metadata = describe(channel, name)
    if value["name"] != metadata["name"]:
        raise WorkspaceError("Artefact name must match its filename")
    return metadata


def instructions(channel: Channel) -> str:
    directory = root(channel, setup=True)
    announce = (
        "After EVERY creation or update, send a separate complete message in this exact format (no surrounding prose):\n"
        if channel.focus_mode else
        "When your completed result is an artefact, use this exact format as your final reply (no surrounding prose). "
        "Finish all work before this reply; omit intermediate announcements:\n"
    )
    return ("\n<lgt_artefacts>\n"
            f"The backend has prepared your artefact directory: {json.dumps(str(directory))}.\n"
            "Use artefacts for substantial plans, handoffs, documents and visualisations; keep normal replies in chat. "
            "Save Markdown (.md), self-contained HTML (.html, embedded CSS/JavaScript), or PDF (.pdf) here. "
            "HTML may load external HTTPS libraries, fonts and images. Never put credentials or secrets in artefacts, "
            "access Lgt/Tauri APIs, or attempt to access or modify the filesystem from a visualisation. "
            "HTML runs isolated: no parent access, storage, fetch/WebSockets, forms, popups or nested frames. "
            "Use script tags for external libraries and embed data. Finish writing before announcing. "
            + announce +
            '```lgt-artefact\n{"name":"plan.md","path":"plan.md"}\n```\n'
            "Use the actual filename and a path relative to the artefact directory (or its absolute path). "
            + ("Announce each file separately. " if channel.focus_mode else
               "Announce the main completed file; other files remain available in the Artefacts panel. ")
            + "Do not move files from other channels.\n</lgt_artefacts>\n")
