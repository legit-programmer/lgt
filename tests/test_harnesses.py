from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from lgt.harnesses import HarnessRegistry
from lgt.models import Agent, Attachment, Channel, Run, Turn, WorkspaceError
from lgt.streaming_adapter import ClaudeRunner, CustomRunner, GeminiRunner, tool_call
from tests.support import settings


FIXTURE = str(Path(__file__).with_name("fake_streaming_cli.py"))


def turn(tmp_path, harness):
    agent = Agent("a", "a", "A", "Helper", harness, "sonnet" if harness == "claude" else "auto", "Help")
    if harness == "custom":
        agent = replace(agent, command=[sys.executable, FIXTURE])
    channel = Channel("c", "channel", "work", str(tmp_path), False)
    run = Run("r", "c", "a", 1, 1, 1, "cold", harness, str(tmp_path))
    return Turn(run, agent, channel, "Hello", None)


@pytest.mark.parametrize("kind,runner", [("claude", ClaudeRunner), ("gemini", GeminiRunner), ("custom", CustomRunner)])
@pytest.mark.asyncio
async def test_streaming_adapters_normalize_subprocess(tmp_path, monkeypatch, kind, runner):
    monkeypatch.setenv("LGT_FAKE_HARNESS", kind)
    instance = runner((sys.executable, FIXTURE), tool_output_cap=7, line_limit=8192,
                      cancel_grace_seconds=.1, log_dir=tmp_path)
    events = [item async for item in instance.start(turn(tmp_path, kind))]
    assert events[-1].data["ok"] is True
    assert next(e for e in events if e.kind == "run_started").data["harness_session_id"] == f"{kind}-1"
    call = next(e for e in events if e.kind == "tool_call")
    result = next(e for e in events if e.kind == "tool_result")
    assert call.data["tool"] in ("read", "bash")
    assert result.data["bytes"] == len("line1\nline2\n" if kind != "custom" else "hello\nworld\n")
    assert result.data["lines"] == 2 and result.data["truncated"]
    report = next(e for e in events if e.kind == "usage").data
    assert report["tokens_in"] > 0
    if kind == "claude":
        assert report["tokens_total"] == 16
    if kind == "custom":
        assert call.data["label"] == "Custom shell"
        assert call.data["summary"] == "Run fixture command"
        assert report["tokens_cached_in"] == 1
        assert report["tokens_cache_creation"] == 3
        assert report["tokens_reasoning"] == 5
        assert report["tokens_total"] == 11
        assert report["context_tokens"] == 100


@pytest.mark.parametrize("trailing", ["invalid", "message", "terminal"])
@pytest.mark.asyncio
async def test_post_terminal_corruption_fails_custom_run(tmp_path, monkeypatch, trailing):
    monkeypatch.setenv("LGT_FAKE_HARNESS", "custom")
    monkeypatch.setenv("LGT_FAKE_TRAILING_CORRUPT", trailing)
    runner = CustomRunner((), tool_output_cap=100, line_limit=8192,
                          cancel_grace_seconds=.1, log_dir=tmp_path)
    events = [event async for event in runner.start(turn(tmp_path, "custom"))]
    assert events[-1].kind == "run_finished"
    assert events[-1].data["ok"] is False
    assert events[-1].data["error"]["code"] == "harness"


def test_custom_terminal_error_keeps_structured_details(tmp_path):
    runner = CustomRunner((), tool_output_cap=100, line_limit=8192,
                          cancel_grace_seconds=.1, log_dir=tmp_path)
    detail = {"code": "auth", "message": "Sign in", "exit_code": 42, "signal": None}
    event = runner.translate({"type": "run_finished", "ok": False, "error": detail, "exit_code": 42})[0]
    assert event.data["error"] == detail
    assert event.data["exit_code"] == 42


def test_tool_names_and_change_summary_are_human_readable():
    assert tool_call("w", "webSearch", {"query": "Python"}).data["tool"] == "web_fetch"
    changed = tool_call("e", "fileChange", {"changes": [{"path": "src/app.py"}]})
    assert changed.data["label"] == "Edit"
    assert "src/app.py" in changed.data["summary"]


@pytest.mark.asyncio
async def test_claude_stream_input_sends_native_image_and_pdf(tmp_path, monkeypatch):
    import base64
    import json

    monkeypatch.setenv("LGT_FAKE_HARNESS", "claude")
    trace = tmp_path / "input.json"
    monkeypatch.setenv("LGT_FAKE_TRACE", str(trace))
    image = tmp_path / "diagram.png"
    pdf = tmp_path / "report.pdf"
    image.write_bytes(b"image")
    pdf.write_bytes(b"pdf")
    attachments = (
        Attachment("i", "c", image.name, "image/png", 5, "", str(image)),
        Attachment("p", "c", pdf.name, "application/pdf", 3, "", str(pdf)),
    )
    selected = replace(turn(tmp_path, "claude"), attachments=attachments)
    runner = ClaudeRunner((sys.executable, FIXTURE), tool_output_cap=100,
                          line_limit=8192, cancel_grace_seconds=.1, log_dir=tmp_path)
    events = [event async for event in runner.start(selected)]
    assert events[-1].data["ok"] is True
    request = json.loads(trace.read_text(encoding="utf-8"))
    blocks = request["message"]["content"]
    assert blocks[0]["text"] == "Hello"
    assert blocks[1]["type"] == "image" and base64.b64decode(blocks[1]["source"]["data"]) == b"image"
    assert blocks[2]["type"] == "document" and base64.b64decode(blocks[2]["source"]["data"]) == b"pdf"


@pytest.mark.asyncio
async def test_registry_rejects_unenforceable_and_unknown_tools(tmp_path):
    registry = HarnessRegistry(settings(tmp_path), claude_command=(sys.executable, FIXTURE),
                               gemini_command=(sys.executable, FIXTURE))
    claude = replace(turn(tmp_path, "claude").agent, allowed_tools=["Read", "Grep"])
    registry.validate_agent(claude)
    with pytest.raises(WorkspaceError, match="unsupported tools"):
        registry.validate_agent(replace(claude, allowed_tools=["Unlisted"]))
    with pytest.raises(WorkspaceError, match="cannot enforce"):
        registry.validate_agent(replace(turn(tmp_path, "gemini").agent, allowed_tools=["Bash"]))
    with pytest.raises(WorkspaceError, match="unsafe"):
        registry.validate_agent(replace(claude, extra_args=["--tools", "Bash"]))
    with pytest.raises(WorkspaceError, match="positive integer"):
        registry.validate_agent(replace(claude, extra_args=["--max-turns", "0"]))
    with pytest.raises(WorkspaceError, match="positive and finite"):
        registry.validate_agent(replace(claude, extra_args=["--max-budget-usd", "NaN"]))
    with pytest.raises(WorkspaceError, match="model"):
        registry.validate_agent(replace(claude, model="imaginary-model"))
    with pytest.raises(WorkspaceError, match="model"):
        registry.validate_agent(replace(turn(tmp_path, "gemini").agent, model="imaginary-model"))
    await registry.prepare_agent(turn(tmp_path, "custom").agent)
    registry.validate_agent(turn(tmp_path, "custom").agent)
    custom = replace(turn(tmp_path, "custom").agent, extra_args=["--profile", "fast"])
    await registry.prepare_agent(custom)
    registry.validate_agent(custom)
    assert registry.runner("custom").argv(replace(turn(tmp_path, "custom"), agent=custom))[-2:] == ("--profile", "fast")
    assert registry.capabilities_for(custom)["resume"] is False


def test_claude_allowlist_restricts_tools_in_command(tmp_path):
    runner = ClaudeRunner((sys.executable, FIXTURE), tool_output_cap=100,
                          line_limit=8192, cancel_grace_seconds=.1, log_dir=tmp_path)
    selected = replace(turn(tmp_path, "claude").agent, allowed_tools=["Read", "Grep"])
    argv = runner.argv(replace(turn(tmp_path, "claude"), agent=selected))
    assert argv[argv.index("--tools") + 1] == "Read,Grep"
    assert argv[argv.index("--disallowedTools") + 1] == "mcp__*"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"


@pytest.mark.asyncio
async def test_registry_scan_finds_cli_without_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv("LGT_FAKE_HARNESS", "claude")
    registry = HarnessRegistry(settings(tmp_path), claude_command=(sys.executable, FIXTURE),
                               gemini_command=(sys.executable, FIXTURE))
    entries = await registry.scan()
    assert {entry["harness"] for entry in entries} == {"codex", "claude", "gemini", "custom"}
    assert next(e for e in entries if e["harness"] == "claude")["auth"] == "signed_in"


@pytest.mark.parametrize("failure", ["malformed", "oversize", "timeout"])
@pytest.mark.asyncio
async def test_custom_probe_rejects_broken_contract_and_reaps_process(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("LGT_FAKE_PROBE", failure)
    registry = HarnessRegistry(settings(tmp_path))
    with pytest.raises(WorkspaceError, match="custom harness probe failed"):
        await registry.probe_custom([sys.executable, FIXTURE])
