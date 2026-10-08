"""Attachment file storage, kept outside every channel's working directory."""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from .models import WorkspaceError

# Image types every supported harness can take as a native image input.
VIEWABLE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_UNSAFE_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVED_NAMES = frozenset({
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
})
_MEDIA_TYPE = re.compile(r"^[\w.+-]+/[\w.+-]+$")


class AttachmentTooLarge(WorkspaceError):
    """The upload exceeded the configured attachment size limit."""


def safe_filename(name: str) -> str:
    """Keep a readable basename that is valid on Windows and POSIX."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE_CHARS.sub("_", base).strip(" .")
    if not base or base.split(".", 1)[0].lower() in _RESERVED_NAMES:
        base = f"file_{base}" if base else "file"
    if len(base) > 200:
        stem, dot, suffix = base.rpartition(".")
        if dot and stem and len(suffix) <= 16:
            base = stem[:200 - len(suffix) - 1] + "." + suffix
        else:
            base = base[:200]
    return base


def normalize_media_type(value: str | None) -> str:
    media_type = (value or "").split(";", 1)[0].strip().lower()
    return media_type if _MEDIA_TYPE.match(media_type) else "application/octet-stream"


async def write_stream(path: Path, chunks: AsyncIterator[bytes], max_bytes: int) -> tuple[int, str]:
    """Write chunks to a new file and return its size and SHA-256 digest.

    The containing directory is removed if the upload fails or exceeds the cap,
    so a rejected upload never leaves a partial file behind.
    """
    path.parent.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("xb") as handle:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise AttachmentTooLarge(f"attachment exceeds the {max_bytes}-byte limit")
                digest.update(chunk)
                handle.write(chunk)
    except BaseException:
        shutil.rmtree(path.parent, ignore_errors=True)
        raise
    return size, digest.hexdigest()


def remove_files(path: str | Path) -> None:
    shutil.rmtree(Path(path).parent, ignore_errors=True)
