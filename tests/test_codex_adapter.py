from __future__ import annotations

from types import SimpleNamespace as NS
import asyncio
from dataclasses import replace
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lgt.codex_adapter import CodexAppServerRunner
from lgt.models import Agent, Channel, Run, Session, Turn


def sample_turn(tmp_path, *, resume=False):
    cwd = str(tmp_path)
    agent = Agent("a", "codex", "Codex", "helper", "codex", "gpt-test", "Be concise.")
    channel = Channel("c", "channel", "work", cwd, False)
    run = Run("r", "c", "a", 1, 1, 1, "resume" if resume else "cold", "codex", cwd)
    session = Session("a", "c", "codex", "thread-1", cwd, 0, "fingerprint", "clean") if resume else None
    return Turn(run, agent, channel, "say hello", session)


def note(method, **payload):
    return NS(method=method, payload=NS(**payload))


class FakeHandle:
    def __init__(self, notes):
        self.notes = notes
        self.interrupted = False

    async def stream(self):
        for event in self.notes:
            yield event

    async def interrupt(self):
        self.interrupted = True


class FakeThread:
    id = "thread-1"

    def __init__(self, handle):
        self.handle = handle
        self.turn_kwargs = None

    async def turn(self, prompt, **kwargs):
        self.turn_kwargs = (prompt, kwargs)
        return self.handle


class FakeClient:
    def __init__(self, handle):
        self.thread = FakeThread(handle)
        self.call = None
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def thread_start(self, **kwargs):
        self.call = ("start", kwargs)
        return self.thread

    async def thread_resume(self, thread_id, **kwargs):
        self.call = ("resume", thread_id, kwargs)
        return self.thread


@pytest.mark.asyncio
async def test_normalizes_stream_and_caps_tool_output(tmp_path):
    notes = [
        note("turn/started", turn=NS(id="t", status="inProgress")),
        note("item/agentMessage/delta", delta="Hi"),
        note("item/started", item={"id": "tool-1", "type": "commandExecution", "command": "echo"}),
        note("item/completed", item={"id": "tool-1", "type": "commandExecution", "aggregatedOutput": "hélö", "status": "completed"}),
        note("item/completed", item={"id": "msg-1", "type": "agentMessage", "text": "Hi there"}),
        note("thread/tokenUsage/updated", token_usage=NS(
            last=NS(input_tokens=7, output_tokens=9), total=NS(input_tokens=100, output_tokens=60),
        )),
        note("thread/tokenUsage/updated", token_usage=NS(
            last=NS(input_tokens=11, output_tokens=15), total=NS(input_tokens=104, output_tokens=66),
        )),
        note("thread/tokenUsage/updated", token_usage=NS(
            last=NS(input_tokens=11, output_tokens=15), total=NS(input_tokens=104, output_tokens=66),
        )),
        note("turn/completed", turn=NS(id="t", status="completed")),
    ]
    client = FakeClient(FakeHandle(notes))
    runner = CodexAppServerRunner(
        tool_output_cap=3, line_limit=1000, cancel_grace_seconds=0.1,
        log_dir=tmp_path, client_factory=lambda _: client,
    )
    events = [e async for e in runner.start(sample_turn(tmp_path))]
    assert [e.kind for e in events] == [
        "run_started", "text_delta", "tool_call", "tool_result", "message", "usage", "usage", "usage", "run_finished",
    ]
    assert events[3].data == {"tool_call_id": "tool-1", "output": "hé", "bytes": 6, "is_error": False}
    assert events[5].data["tokens_in"] == 7
    assert events[6].data["tokens_in"] == 4
    assert events[7].data == {"tokens_in": 0, "tokens_out": 0}
    assert events[-1].data["ok"] is True
    assert client.call[0] == "start"
    assert "home base" in client.call[1]["developer_instructions"]
    assert client.closed


@pytest.mark.asyncio
async def test_resume_uses_saved_thread_and_bypasses_approvals(tmp_path):
    from openai_codex import ApprovalMode, Sandbox

    client = FakeClient(FakeHandle([note("turn/completed", turn=NS(id="t", status="completed"))]))
    runner = CodexAppServerRunner(
        tool_output_cap=100, line_limit=1000, cancel_grace_seconds=0.1,
        log_dir=tmp_path, client_factory=lambda _: client,
    )
    events = [e async for e in runner.start(sample_turn(tmp_path, resume=True))]
    assert client.call[0:2] == ("resume", "thread-1")
    assert client.call[2]["approval_mode"] == ApprovalMode.deny_all
    assert client.call[2]["sandbox"] == Sandbox.full_access
    assert client.thread.turn_kwargs[1]["approval_mode"] == ApprovalMode.deny_all
    assert client.thread.turn_kwargs[1]["sandbox"] == Sandbox.full_access
    assert events[-1].data["ok"] is True


@pytest.mark.asyncio
async def test_missing_completion_is_failed(tmp_path):
    client = FakeClient(FakeHandle([note("item/agentMessage/delta", delta="partial")]))
    runner = CodexAppServerRunner(
        tool_output_cap=100, line_limit=1000, cancel_grace_seconds=0.1,
        log_dir=tmp_path, client_factory=lambda _: client,
    )
    events = [e async for e in runner.start(sample_turn(tmp_path))]
    assert events[-1].kind == "run_finished"
    assert events[-1].data["ok"] is False


@pytest.mark.asyncio
async def test_completed_only_tool_keeps_output_out_of_call_input(tmp_path):
    output = "é" * 1000
    client = FakeClient(FakeHandle([
        note("item/completed", item={
            "id": "tool-1", "type": "commandExecution", "command": "echo",
            "aggregatedOutput": output, "status": "completed", "exitCode": 0,
        }),
        note("turn/completed", turn=NS(id="t", status="completed")),
    ]))
    runner = CodexAppServerRunner(
        tool_output_cap=11, line_limit=10000, cancel_grace_seconds=0.1,
        log_dir=tmp_path, client_factory=lambda _: client,
    )
    events = [e async for e in runner.start(sample_turn(tmp_path))]
    call = next(e for e in events if e.kind == "tool_call")
    result = next(e for e in events if e.kind == "tool_result")
    assert call.data["input"] == {"id": "tool-1", "type": "commandExecution", "command": "echo"}
    assert result.data["bytes"] == 2000
    assert result.data["output"] == "é" * 5


@pytest.mark.asyncio
async def test_startup_timeout_fails_run(tmp_path):
    class SlowClient(FakeClient):
        async def __aenter__(self):
            await asyncio.sleep(10)
            return self

    client = SlowClient(FakeHandle([]))
    runner = CodexAppServerRunner(
        tool_output_cap=100, line_limit=1000, cancel_grace_seconds=0.1,
        startup_timeout_seconds=0.02, log_dir=tmp_path,
        client_factory=lambda _: client,
    )
    events = [e async for e in runner.start(sample_turn(tmp_path))]
    assert events[-1].data["ok"] is False
    assert "startup request timed out" in events[-1].data["error"]
    assert client.closed


@pytest.mark.asyncio
async def test_turn_setup_failure_keeps_thread_identity_for_dirty_session(tmp_path):
    client = FakeClient(FakeHandle([]))

    async def fail_turn(*args, **kwargs):
        raise RuntimeError("turn setup failed after resume")

    client.thread.turn = fail_turn
    runner = CodexAppServerRunner(
        tool_output_cap=100, line_limit=1000, cancel_grace_seconds=0.1,
        log_dir=tmp_path, client_factory=lambda _: client,
    )
    events = [e async for e in runner.start(sample_turn(tmp_path, resume=True))]
    assert events[0].kind == "run_started"
    assert events[0].data["harness_session_id"] == "thread-1"
    assert events[-1].data["ok"] is False
    assert client.closed


@pytest.mark.asyncio
async def test_real_sdk_fixture_through_bounded_host(tmp_path, monkeypatch):
    from lgt import sdk_host

    fixture = Path(__file__).with_name("fake_codex_sdk_server.py")
    trace = tmp_path / "requests.jsonl"
    log = tmp_path / "fixture.stderr.log"
    monkeypatch.setenv("CODEX_FAKE_TRACE", str(trace))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    runner = CodexAppServerRunner(
        tool_output_cap=100, line_limit=1024 * 1024, cancel_grace_seconds=0.2,
        log_dir=tmp_path,
        launch_args_override=(
            sys.executable, str(Path(sdk_host.__file__)),
            "--log", str(log), "--line-limit", str(1024 * 1024),
            "--", sys.executable, str(fixture),
        ),
    )
    events = [event async for event in runner.start(sample_turn(tmp_path))]
    assert events[-1].data["ok"] is True, events[-1].data
    assert any(event.kind == "process_started" for event in events)
    assert any(event.kind == "text_delta" and event.data["text"] == "Hello" for event in events)
    assert any(event.kind == "message" and event.data["text"] == "Hello from SDK" for event in events)
    assert any(event.kind == "usage" and event.data["tokens_in"] == 7 for event in events)
    requests = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    thread_request = next(request for request in requests if request.get("method") == "thread/start")
    assert thread_request["params"]["approvalPolicy"] == "never"
    assert thread_request["params"]["sandbox"] == "danger-full-access"
    assert log.stat().st_size > 65536


@pytest.mark.asyncio
async def test_sdk_interrupt_marks_cancelled(tmp_path, monkeypatch):
    from lgt import sdk_host

    fixture = Path(__file__).with_name("fake_codex_sdk_server.py")
    monkeypatch.setenv("CODEX_FAKE_TRACE", str(tmp_path / "requests.jsonl"))
    runner = CodexAppServerRunner(
        tool_output_cap=100, line_limit=1024 * 1024, cancel_grace_seconds=1,
        log_dir=tmp_path,
        launch_args_override=(
            sys.executable, str(Path(sdk_host.__file__)),
            "--log", str(tmp_path / "stderr.log"), "--line-limit", str(1024 * 1024),
            "--", sys.executable, str(fixture),
        ),
    )
    turn = replace(sample_turn(tmp_path), prompt="hold")
    ready = asyncio.Event()
    events = []

    async def collect():
        async for event in runner.start(turn):
            events.append(event)
            if event.kind == "run_started":
                ready.set()

    task = asyncio.create_task(collect())
    await asyncio.wait_for(ready.wait(), 5)
    await runner.cancel("user")
    await asyncio.wait_for(task, 5)
    assert events[-1].data["cancelled"] is True
    assert events[-1].data["ok"] is False


@pytest.mark.asyncio
async def test_sdk_host_rejects_oversized_line(tmp_path, monkeypatch):
    from lgt import sdk_host

    fixture = Path(__file__).with_name("fake_codex_sdk_server.py")
    monkeypatch.setenv("CODEX_FAKE_TRACE", str(tmp_path / "requests.jsonl"))
    log = tmp_path / "stderr.log"
    runner = CodexAppServerRunner(
        tool_output_cap=100, line_limit=512, cancel_grace_seconds=0.2,
        log_dir=tmp_path,
        launch_args_override=(
            sys.executable, str(Path(sdk_host.__file__)),
            "--log", str(log), "--line-limit", "512",
            "--", sys.executable, str(fixture),
        ),
    )
    events = [event async for event in runner.start(replace(sample_turn(tmp_path), prompt="oversize"))]
    assert events[-1].data["ok"] is False
    assert "exceeds 512 bytes" in log.read_text(encoding="utf-8", errors="replace")


def test_sdk_host_stdin_eof_stops_child_ignoring_eof(tmp_path):
    from lgt import sdk_host

    child_code = "import os,time; print(os.getpid(), flush=True); time.sleep(60)"
    host = subprocess.Popen(
        [
            sys.executable, str(Path(sdk_host.__file__)),
            "--log", str(tmp_path / "stderr.log"), "--line-limit", "100",
            "--", sys.executable, "-c", child_code,
        ],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=tmp_path,
    )
    try:
        child_pid = int(host.stdout.readline())
        host.stdin.close()
        host.wait(timeout=4)
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {child_pid}", "/FO", "CSV"],
                capture_output=True, text=True, check=True,
            )
            assert f'"{child_pid}"' not in result.stdout
        else:
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
    finally:
        if host.poll() is None:
            host.kill()
            host.wait()
