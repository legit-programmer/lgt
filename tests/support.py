from __future__ import annotations

import asyncio
from pathlib import Path

from lgt.config import Settings
from lgt.models import NormalizedEvent, RoutingDecision


def settings(data_dir: Path, **overrides) -> Settings:
    values = dict(
        data_dir=data_dir, max_hops=3, tool_output_cap=65536, concurrent_runs=4,
        replay_cap=5000, router_timeout_seconds=1, router_context_events=50,
        route_after_active=False, session_ttl_seconds=None, router_model="haiku",
        codex_router_model=None, router_attempts=2, ndjson_line_limit=1048576,
        cancel_grace_seconds=0.1, checkpoint_threshold=100000,
        checkpoint_tail_chars=25000, checkpoint_summary_chars=10000,
        attachment_max_bytes=1048576,
    )
    values.update(overrides)
    return Settings(**values)


class ControlledRunner:
    def __init__(self, factory):
        self.factory = factory
        self.outputs = asyncio.Queue()
        self.turn = None
        self.cancelled = False

    async def start(self, turn):
        self.turn = turn
        self.factory.started.append(self)
        yield NormalizedEvent("run_started", {"harness_session_id": f"session-{turn.run.run_id}"})
        while True:
            output = await self.outputs.get()
            yield output
            if output.kind == "run_finished":
                return

    async def cancel(self, reason):
        self.cancelled = True
        self.outputs.put_nowait(NormalizedEvent("run_finished", {"ok": False, "cancelled": True}))

    def emit(self, kind, **data):
        self.outputs.put_nowait(NormalizedEvent(kind, data))

    def finish(self, text="done", ok=True):
        if text:
            self.emit("message", text=text)
        self.emit("run_finished", ok=ok, exit_code=0 if ok else 1)


class ControlledFactory:
    def __init__(self):
        self.started = []

    def __call__(self, harness):
        return ControlledRunner(self)


class FakeRouter:
    def __init__(self, picks=None):
        self.picks = picks or []
        self.calls = []

    async def route(self, request):
        self.calls.append(request)
        return RoutingDecision(self.picks, "fixture")


async def eventually(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)
