"""Structured failures and the text shown in the workspace event log."""

from __future__ import annotations

import signal as signals
from datetime import datetime
from typing import Any


def duration_ms(started_at: str | None, ended_at: str) -> int | None:
    if not started_at:
        return None
    return max(0, int((datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds() * 1000))


def normalize_error(error: Any, exit_code: int | None = None) -> dict[str, Any]:
    details = dict(error) if isinstance(error, dict) else {"message": str(error or "Harness run failed")}
    message = str(details.get("message") or "Harness run failed")
    if details.get("exit_code") is not None:
        exit_code = details["exit_code"]
    signal = details.get("signal")
    if signal is None and isinstance(exit_code, int) and exit_code < 0:
        try:
            signal = signals.Signals(-exit_code).name
        except ValueError:
            signal = str(-exit_code)
    lowered = message.lower()
    # A SIGKILL/137 alone cannot prove OOM. Use the harness's diagnostics.
    code = details.get("code")
    if not code:
        if "out of memory" in lowered or "oom" in lowered:
            code = "oom"
        elif "orphan" in lowered:
            code = "orphaned"
        elif "auth" in lowered or "sign in" in lowered or "not logged" in lowered or "unauthorized" in lowered:
            code = "auth"
        elif "timeout" in lowered or "timed out" in lowered:
            code = "timeout"
        elif signal is not None:
            code = "signal"
        elif "cancel" in lowered:
            code = "cancelled"
        else:
            code = "harness"
    return {"code": code, "message": message, "exit_code": exit_code, "signal": signal}


def failure_text(harness: str, error: dict[str, Any], elapsed_ms: int | None) -> str:
    text = harness
    if error.get("signal"):
        text += f" stopped by {error['signal']}"
    elif error.get("exit_code") is not None:
        text += f" exited {error['exit_code']}"
    else:
        text += " failed"
    detail = "out of memory" if error["code"] == "oom" else error["message"]
    text += f" ({detail})"
    if elapsed_ms is not None:
        seconds = elapsed_ms // 1000
        minutes, seconds = divmod(seconds, 60)
        text += f" after {minutes}m {seconds}s" if minutes else f" after {seconds}s"
    return text
