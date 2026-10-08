"""Schema-valid app-server fixture for the pinned official Python SDK."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


TRACE = Path(os.environ["CODEX_FAKE_TRACE"])


def send(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def record(value):
    with TRACE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(value) + "\n")


def reply(request, result):
    send({"jsonrpc": "2.0", "id": request["id"], "result": result})


def notify(method, params):
    send({"jsonrpc": "2.0", "method": method, "params": params})


def thread(cwd):
    return {
        "cliVersion": "0.160.1", "createdAt": 1, "updatedAt": 1,
        "cwd": cwd, "ephemeral": False, "id": "thread-1", "modelProvider": "openai",
        "preview": "fixture", "sessionId": "thread-1", "source": "appServer",
        "status": {"type": "idle"}, "turns": [],
    }


def main():
    # Forces the proxy's concurrent stderr drain during initialization.
    sys.stderr.write("diagnostic " * 30_000)
    sys.stderr.flush()
    cwd = str(Path.cwd())
    active_turn = None
    while line := sys.stdin.readline():
        request = json.loads(line)
        record(request)
        method = request.get("method")
        params = request.get("params") or {}
        if method == "initialize":
            reply(request, {"serverInfo": {"name": "fake", "version": "0.160.1"},
                            "userAgent": "fake/0.160.1"})
        elif method == "initialized":
            pass
        elif method in ("thread/start", "thread/resume"):
            answer = {
                "thread": thread(cwd), "approvalPolicy": "never",
                "approvalsReviewer": "user", "cwd": cwd, "model": "gpt-test",
                "modelProvider": "openai", "sandbox": {"type": "dangerFullAccess"},
            }
            reply(request, answer)
        elif method == "turn/start":
            turn_id = "turn-1"
            turn = {"id": turn_id, "items": [], "status": "inProgress"}
            prompt = " ".join(item.get("text", "") for item in params.get("input", []))
            reply(request, {"turn": turn})
            notify("turn/started", {"threadId": "thread-1", "turn": turn})
            if "hold" in prompt:
                active_turn = turn_id
                continue
            if "eof" in prompt:
                return
            if "oversize" in prompt:
                notify("item/agentMessage/delta", {
                    "threadId": "thread-1", "turnId": turn_id,
                    "itemId": "message-1", "delta": "x" * 4096,
                })
                return
            notify("item/agentMessage/delta", {
                "threadId": "thread-1", "turnId": turn_id,
                "itemId": "message-1", "delta": "Hello",
            })
            notify("item/completed", {
                "threadId": "thread-1", "turnId": turn_id, "completedAtMs": 2,
                "item": {"id": "message-1", "type": "agentMessage", "text": "Hello from SDK"},
            })
            notify("thread/tokenUsage/updated", {
                "threadId": "thread-1", "turnId": turn_id,
                "tokenUsage": {
                    "last": {"inputTokens": 7, "outputTokens": 3, "cachedInputTokens": 0,
                             "reasoningOutputTokens": 0, "totalTokens": 10},
                    "total": {"inputTokens": 100, "outputTokens": 50, "cachedInputTokens": 0,
                              "reasoningOutputTokens": 0, "totalTokens": 150},
                },
            })
            notify("turn/completed", {
                "threadId": "thread-1", "turn": {"id": turn_id, "items": [], "status": "completed"},
            })
        elif method == "turn/interrupt":
            reply(request, {})
            if active_turn:
                notify("turn/completed", {
                    "threadId": "thread-1",
                    "turn": {"id": active_turn, "items": [], "status": "interrupted"},
                })
                active_turn = None
        else:
            send({"jsonrpc": "2.0", "id": request.get("id"),
                  "error": {"code": -32601, "message": method}})


if __name__ == "__main__":
    main()
