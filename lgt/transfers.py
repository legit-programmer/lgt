"""Explicit agent transfer protocol shared by every harness."""
from __future__ import annotations

import json
import re
from typing import Any

from .models import WorkspaceError


def without_code(text: str) -> str:
    """Mask Markdown code while retaining line boundaries for mention parsing."""
    lines = text.splitlines(keepends=True)
    fence: tuple[str, int] | None = None
    visible: list[str] = []
    for line in lines:
        if re.match(r"^ {0,3}>", line):
            # Quoted messages and examples are background, never instructions.
            visible.append("\n" if line.endswith("\n") else "")
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}\s*", line):
                fence = None
            visible.append("\n" if line.endswith("\n") else "")
        elif opening:
            fence = (opening[1][0], len(opening[1]))
            visible.append("\n" if line.endswith("\n") else "")
        elif line.startswith(("    ", "\t")):
            visible.append("\n" if line.endswith("\n") else "")
        else:
            visible.append(line)
    # A matching run of backticks delimits inline code (including multiline spans).
    prose = re.sub(r"\\[\\`<>]", " ", "".join(visible))
    return re.sub(r"(?<!`)(`+)(?!`)(.*?)(?<!`)\1(?!`)", " ", prose, flags=re.DOTALL)


def parse_inline_transfers(text: str) -> list[dict[str, str]]:
    """Read typed mentions from ordinary prose, never from Markdown code."""
    transfers = [{"mode": match[2], "target": match[1], "text": text}
                 for match in re.finditer(r"<@([\w.:-]+):(handoff|delegation)>", without_code(text))]
    if sum(item["mode"] == "handoff" for item in transfers) > 1:
        raise WorkspaceError("an agent message can request at most one handoff")
    if len({item["target"] for item in transfers}) != len(transfers):
        raise WorkspaceError("an agent message can transfer to each target only once")
    return transfers


def message_transfers(payload: dict) -> list[dict]:
    """Read both current plural metadata and persisted legacy transfers."""
    return payload.get("transfers") or ([payload["transfer"]] if payload.get("transfer") else [])


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
