"""Small JSONL app-server fixture used by ``test_codex_adapter``.

It deliberately emits turn notifications before the ``turn/start`` response,
as a real app-server is allowed to do. Set ``CODEX_FAKE_TRACE`` to record the
requests and responses observed by this process.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


TRACE = Path(os.environ["CODEX_FAKE_TRACE"])


def record(value: dict[str, Any]) -> None:
    with TRACE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def send(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def notification(method: str, params: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "method": method, "params": params})


def response(request_id: Any, result: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def token_usage(thread_id: str, turn_id: str, total_in: int, total_out: int, last_in: int, last_out: int) -> None:
    notification(
        "thread/tokenUsage/updated",
        {
            "threadId": thread_id,
            "turnId": turn_id,
            "tokenUsage": {
                "total": {
                    "inputTokens": total_in,
                    "outputTokens": total_out,
                    "cachedInputTokens": 0,
                    "reasoningOutputTokens": 0,
                    "totalTokens": total_in + total_out,
                },
                "last": {
                    "inputTokens": last_in,
                    "outputTokens": last_out,
                    "cachedInputTokens": 0,
                    "reasoningOutputTokens": 0,
                    "totalTokens": last_in + last_out,
                },
            },
        },
    )


def read_approval_response(request_id: str) -> None:
    while line := sys.stdin.readline():
        message = json.loads(line)
        record(message)
        if message.get("id") == request_id:
            return


def main() -> None:
    # Exceed the typical Windows pipe buffer before the handshake. The adapter
    # must drain stderr concurrently or initialization will deadlock.
    sys.stderr.write("diagnostic " * 30_000)
    sys.stderr.flush()

    thread_counter = 0
    turn_counter = 0
    active: tuple[str, str] | None = None

    while line := sys.stdin.readline():
        request = json.loads(line)
        record(request)
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if method == "initialize":
            response(request_id, {"serverInfo": {"name": "fake-codex", "version": "1"}})
        elif method == "initialized":
            continue
        elif method == "thread/start":
            thread_counter += 1
            thread_id = f"thread-{thread_counter}"
            notification("thread/started", {"thread": {"id": thread_id}})
            response(request_id, {"thread": {"id": thread_id}})
        elif method == "thread/resume":
            thread_id = params["threadId"]
            response(request_id, {"thread": {"id": thread_id}})
        elif method == "turn/start":
            turn_counter += 1
            thread_id = params["threadId"]
            turn_id = f"turn-{turn_counter}"
            inputs = params.get("input", [])
            message_text = " ".join(item.get("text", "") for item in inputs if item.get("type") == "text")

            notification(
                "turn/started",
                {"threadId": thread_id, "turn": {"id": turn_id, "status": "inProgress"}},
            )

            if "hold" in message_text:
                active = (thread_id, turn_id)
                response(request_id, {"turn": {"id": turn_id}})
                continue

            if "eof" in message_text:
                response(request_id, {"turn": {"id": turn_id}})
                time.sleep(0.25)
                return

            if "error" in message_text:
                notification(
                    "error",
                    {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "error": {"message": "mock model failed"},
                        "willRetry": False,
                    },
                )
                notification(
                    "turn/completed",
                    {"threadId": thread_id, "turn": {"id": turn_id, "status": "failed"}},
                )
                response(request_id, {"turn": {"id": turn_id}})
                continue

            # Server-initiated approval is answered by the adapter's default
            # policy. The request is interleaved before the turn response.
            approval_id = f"approval-{turn_counter}"
            send(
                {
                    "jsonrpc": "2.0",
                    "id": approval_id,
                    "method": "item/commandExecution/requestApproval",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "itemId": "exec-1",
                        "command": ["echo", "fixture"],
                        "cwd": str(Path.cwd()),
                        "reason": "fixture approval",
                    },
                }
            )
            read_approval_response(approval_id)

            notification(
                "item/agentMessage/delta",
                {"threadId": thread_id, "turnId": turn_id, "itemId": "msg-1", "delta": "Hello "},
            )
            notification(
                "item/started",
                {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {
                        "id": "exec-1",
                        "type": "commandExecution",
                        "command": ["echo", "fixture"],
                        "cwd": str(Path.cwd()),
                        "status": "inProgress",
                    },
                },
            )
            notification(
                "item/completed",
                {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {
                        "id": "exec-1",
                        "type": "commandExecution",
                        "command": ["echo", "fixture"],
                        "cwd": str(Path.cwd()),
                        "aggregatedOutput": "hé\n",
                        "status": "declined",
                    },
                },
            )
            notification(
                "item/completed",
                {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {"id": "msg-1", "type": "agentMessage", "text": "Hello from Codex"},
                },
            )
            # The total already includes historical usage. The first event
            # therefore contributes only last; subsequent events use deltas.
            token_usage(thread_id, turn_id, 100, 60, 7, 9)
            token_usage(thread_id, turn_id, 104, 66, 4, 6)
            notification(
                "turn/completed",
                {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}},
            )
            response(request_id, {"turn": {"id": turn_id}})
        elif method == "turn/interrupt":
            thread_id, turn_id = active or (params.get("threadId", ""), params.get("turnId", ""))
            notification(
                "turn/completed",
                {"threadId": thread_id, "turn": {"id": turn_id, "status": "interrupted"}},
            )
            response(request_id, {})
            active = None
        else:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown fixture method: {method}"},
                }
            )


if __name__ == "__main__":
    main()
