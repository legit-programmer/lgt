"""Small subprocess fixture for all three NDJSON adapter protocols."""
import json
import os
import sys
import time


def send(value):
    print(json.dumps(value), flush=True)


mode = os.environ.get("LGT_FAKE_HARNESS", "gemini")
if "--version" in sys.argv:
    print("fixture 1.0")
elif "--help" in sys.argv:
    print("--output-format stream-json --resume --tools --input-format")
elif "--lgt-probe" in sys.argv:
    if os.environ.get("LGT_FAKE_PROBE") == "malformed":
        print("not json")
        sys.exit(0)
    if os.environ.get("LGT_FAKE_PROBE") == "oversize":
        print("x" * 70000)
        sys.exit(0)
    if os.environ.get("LGT_FAKE_PROBE") == "timeout":
        time.sleep(60)
        sys.exit(0)
    send({"type": "probe", "contract_version": 1,
          "capabilities": {"resume": False, "interrupt": True, "text_delta": True,
                           "allowed_tools": False, "image_input": True, "usage": True, "rate_limits": True},
          "models": [{"id": "auto", "label": "Auto", "description": "Fixture", "default": True}],
          "tools": []})
elif mode == "claude" and sys.argv[1:3] == ["auth", "status"]:
    print('{"authMethod":"claude.ai"}')
elif mode == "custom":
    request = json.loads(sys.stdin.readline())
    send({"type": "run_started", "session_id": "custom-1"})
    send({"type": "tool_call", "tool_call_id": "t1", "tool": "Bash", "label": "Custom shell",
          "summary": "Run fixture command", "input": {"command": "echo hi"}})
    send({"type": "tool_result", "tool_call_id": "t1", "output": "hello\nworld\n"})
    send({"type": "usage", "tokens_in": 4, "tokens_out": 2, "tokens_cached_in": 1,
          "tokens_cache_creation": 3, "tokens_reasoning": 5, "tokens_total": 11,
          "context_tokens": 100, "model_context_window": 200})
    send({"type": "run_finished", "ok": request["type"] == "turn"})
    if trailing := os.environ.get("LGT_FAKE_TRAILING_CORRUPT"):
        if trailing == "message":
            send({"type": "message", "text": "Too late"})
        elif trailing == "terminal":
            send({"type": "run_finished", "ok": True})
        else:
            print("not-json", flush=True)
elif mode == "claude":
    if path := os.environ.get("LGT_FAKE_TRACE"):
        with open(path, "w", encoding="utf-8") as trace:
            trace.write(sys.stdin.readline())
    send({"type": "system", "session_id": "claude-1"})
    send({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}})
    send({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a.py"}},
        {"type": "text", "text": "Done"}]}})
    send({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "line1\nline2\n"}]}})
    send({"type": "result", "is_error": False, "usage": {"input_tokens": 10, "output_tokens": 3,
          "cache_read_input_tokens": 2, "cache_creation_input_tokens": 1}})
else:
    send({"type": "init", "session_id": "gemini-1"})
    send({"type": "message", "role": "assistant", "content": "Hi", "delta": True})
    send({"type": "tool_use", "tool_id": "t1", "tool_name": "run_shell_command", "parameters": {"command": "echo hi"}})
    send({"type": "tool_result", "tool_id": "t1", "status": "success", "output": "line1\nline2\n"})
    send({"type": "result", "status": "success", "stats": {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9}})
