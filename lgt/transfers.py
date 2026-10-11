"""Explicit agent transfer protocol shared by every harness."""
from __future__ import annotations

import json
import re
from typing import Any

from .models import WorkspaceError


def parse_transfer(text: str, structured: Any = None) -> dict[str, str] | None:
    """Only a complete control message can transfer work; quoted examples cannot."""
    match = re.fullmatch(r"\s*```lgt-transfer\s*\n(.*?)\n```\s*", text, re.DOTALL)
    if structured is None and match is None:
        return None
    try:
        value = structured if structured is not None else json.loads(match[1])
    except ValueError as error:
        raise WorkspaceError("invalid agent transfer JSON") from error
    if (not isinstance(value, dict) or set(value) != {"mode", "target", "text"}
            or not isinstance(value.get("mode"), str)
            or value.get("mode") not in {"handoff", "delegation"}
            or any(not isinstance(value.get(key), str) or not value[key].strip()
                   for key in ("target", "text"))):
        raise WorkspaceError("agent transfer requires mode, target and text")
    return value
