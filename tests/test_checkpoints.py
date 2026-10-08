from __future__ import annotations

import asyncio

import pytest

from lgt.context import cold_plan, render_delta, render_turn
from lgt.models import Agent
from lgt.orchestrator import Orchestrator
from lgt.store import Store
from tests.support import ControlledFactory, FakeRouter, eventually, settings


class DeferredSummarizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.pending: list[asyncio.Future[str]] = []

    async def summarize(self, prompt: str, max_chars: int) -> str:
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.calls.append((prompt, max_chars))
        self.pending.append(future)
        return await future

    def resolve(self, index: int, summary: str) -> None:
        self.pending[index].set_result(summary)

    def fail(self, index: int, error: Exception) -> None:
        self.pending[index].set_exception(error)


@pytest.fixture
async def checkpoint_workspace(tmp_path):
    store = Store(tmp_path / "checkpoint.sqlite3")
    runner_factory = ControlledFactory()
    summarizer = DeferredSummarizer()
    orch = Orchestrator(
        store,
        settings(
            tmp_path,
            checkpoint_threshold=80,
            checkpoint_tail_chars=30,
            checkpoint_summary_chars=128,
        ),
        FakeRouter(["alpha"]),
        runner_factory,
        lambda _harness, _session_id, _cwd: True,
        human_id="local",
        summarizer=summarizer,
    )
    orch.put_agent(Agent("alpha", "alpha", "Alpha", "specialist", "codex", "", "help"))
    channel = orch.create_channel("checkpoint tests", agent_ids=["alpha"])
    await orch.start()
    yield orch, store, runner_factory, channel, summarizer
    await orch.close()
    store.close()


async def start_and_finish(orch, factory, channel, text: str, answer: str = "recent raw answer"):
    await orch.send_message(channel.channel_id, text, ["alpha"])
    await eventually(lambda: bool(factory.started))
    runner = factory.started[-1]
    runner.finish(answer)
    await eventually(lambda: runner.turn.run.run_id not in orch._run_tasks)
    return runner


def checkpoint_events(store, channel_id: str):
    return [event for event in store.events(channel_id) if event.kind == "context_checkpoint"]


@pytest.mark.asyncio
async def test_async_checkpoint_keeps_its_captured_covers_seq_when_messages_arrive(tmp_path):
    store = Store(tmp_path / "captured.sqlite3")
    runner_factory = ControlledFactory()
    summarizer = DeferredSummarizer()
    orch = Orchestrator(
        store,
        settings(tmp_path, checkpoint_threshold=80, checkpoint_tail_chars=30, checkpoint_summary_chars=128),
        FakeRouter(), runner_factory, lambda *_: True, human_id="local", summarizer=summarizer,
    )
    orch.put_agent(Agent("alpha", "alpha", "Alpha", "specialist", "codex", "", "help"))
    channel = orch.create_channel("captured", agent_ids=["alpha"])
    await orch.start()
    old_text = "OLD TASK " + ("long context " * 16)
    try:
        await start_and_finish(orch, runner_factory, channel, old_text)
        await eventually(lambda: len(summarizer.calls) == 1)
        summary_prompt, max_chars = summarizer.calls[0]
        assert old_text in summary_prompt
        assert max_chars == 128
        snapshot_end = store.get_channel(channel.channel_id).next_seq - 1

        intervening = await orch._call(
            channel.channel_id,
            lambda: orch._append(
                channel.channel_id, "message", "human", "local",
                {"text": "ARRIVED WHILE SUMMARY WAS PENDING", "mentions": []},
            ),
        )
        assert intervening.seq > snapshot_end
        assert "ARRIVED WHILE SUMMARY WAS PENDING" not in summary_prompt
        summarizer.resolve(0, "Summary of the earlier conversation")
        await eventually(lambda: len(checkpoint_events(store, channel.channel_id)) == 1)

        checkpoint = checkpoint_events(store, channel.channel_id)[0]
        assert checkpoint.seq > intervening.seq > checkpoint.payload["covers_through_seq"]
        plan = cold_plan(store.events(channel.channel_id))
        assert plan.start_seq == checkpoint.payload["covers_through_seq"] + 1
        raw_tail = render_delta(
            store, "alpha", channel.channel_id, plan.start_seq, checkpoint.seq, "cold",
        )
        assert "ARRIVED WHILE SUMMARY WAS PENDING" in raw_tail
    finally:
        await orch.close()
        store.close()


@pytest.mark.asyncio
async def test_checkpoint_retains_the_recent_raw_tail_for_cold_rebuild(tmp_path):
    store = Store(tmp_path / "tail.sqlite3")
    runner_factory = ControlledFactory()
    summarizer = DeferredSummarizer()
    orch = Orchestrator(
        store,
        settings(tmp_path, checkpoint_threshold=80, checkpoint_tail_chars=30, checkpoint_summary_chars=128),
        FakeRouter(), runner_factory, lambda *_: True, human_id="local", summarizer=summarizer,
    )
    orch.put_agent(Agent("alpha", "alpha", "Alpha", "specialist", "codex", "", "help"))
    channel = orch.create_channel("raw tail", agent_ids=["alpha"])
    await orch.start()
    old_text = "SUMMARIZED OLD MATERIAL " + ("obsolete detail " * 12)
    try:
        runner = await start_and_finish(orch, runner_factory, channel, old_text, "RECENT EXACT ANSWER")
        await eventually(lambda: len(summarizer.calls) == 1)
        summarizer.resolve(0, "SUMMARY OF OLD MATERIAL")
        await eventually(lambda: len(checkpoint_events(store, channel.channel_id)) == 1)

        checkpoint = checkpoint_events(store, channel.channel_id)[0]
        answer = next(
            event for event in store.events(channel.channel_id)
            if event.kind == "message" and event.author_id == "alpha"
        )
        assert checkpoint.payload["covers_through_seq"] < answer.seq
        plan = cold_plan(store.events(channel.channel_id))
        assert plan.summary == "SUMMARY OF OLD MATERIAL"
        rendered = render_turn(store, runner.turn.agent, channel, plan, checkpoint.seq)
        assert "SUMMARY OF OLD MATERIAL" in rendered
        assert "RECENT EXACT ANSWER" in rendered
        assert old_text not in rendered
    finally:
        await orch.close()
        store.close()


@pytest.mark.asyncio
async def test_rolling_checkpoint_prompt_includes_the_previous_summary(tmp_path):
    store = Store(tmp_path / "rolling.sqlite3")
    runner_factory = ControlledFactory()
    summarizer = DeferredSummarizer()
    orch = Orchestrator(
        store,
        settings(tmp_path, checkpoint_threshold=80, checkpoint_tail_chars=30, checkpoint_summary_chars=128),
        FakeRouter(), runner_factory, lambda *_: True, human_id="local", summarizer=summarizer,
    )
    orch.put_agent(Agent("alpha", "alpha", "Alpha", "specialist", "codex", "", "help"))
    channel = orch.create_channel("rolling", agent_ids=["alpha"])
    await orch.start()
    try:
        await start_and_finish(orch, runner_factory, channel, "FIRST CONTEXT " + ("detail " * 20), "first reply")
        await eventually(lambda: len(summarizer.calls) == 1)
        summarizer.resolve(0, "FIRST ROLLING SUMMARY")
        await eventually(lambda: len(checkpoint_events(store, channel.channel_id)) == 1)

        second_text = "SECOND CONTEXT " + ("new detail " * 20)
        await orch.send_message(channel.channel_id, second_text, ["alpha"])
        await eventually(lambda: len(runner_factory.started) == 2)
        second_runner = runner_factory.started[1]
        second_runner.finish("second reply")
        await eventually(lambda: second_runner.turn.run.run_id not in orch._run_tasks)
        await eventually(lambda: len(summarizer.calls) == 2)
        second_prompt, _ = summarizer.calls[1]
        assert "Previous summary:\nFIRST ROLLING SUMMARY" in second_prompt
        summarizer.resolve(1, "SECOND ROLLING SUMMARY")
        await eventually(lambda: len(checkpoint_events(store, channel.channel_id)) == 2)
        assert cold_plan(store.events(channel.channel_id)).summary == "SECOND ROLLING SUMMARY"
    finally:
        await orch.close()
        store.close()


@pytest.mark.parametrize("change", ["reset", "edit"])
@pytest.mark.asyncio
async def test_reset_or_edit_to_covered_seq_while_pending_rejects_stale_checkpoint(tmp_path, change):
    store = Store(tmp_path / f"stale-{change}.sqlite3")
    runner_factory = ControlledFactory()
    summarizer = DeferredSummarizer()
    orch = Orchestrator(
        store,
        settings(tmp_path, checkpoint_threshold=80, checkpoint_tail_chars=30, checkpoint_summary_chars=128),
        FakeRouter(), runner_factory, lambda *_: True, human_id="local", summarizer=summarizer,
    )
    orch.put_agent(Agent("alpha", "alpha", "Alpha", "specialist", "codex", "", "help"))
    channel = orch.create_channel(f"stale {change}", agent_ids=["alpha"])
    await orch.start()
    old_text = "COVERED MESSAGE " + ("important history " * 15)
    try:
        original = await orch.send_message(channel.channel_id, old_text, ["alpha"])
        await eventually(lambda: len(runner_factory.started) == 1)
        runner = runner_factory.started[0]
        runner.finish("recent answer")
        await eventually(lambda: runner.turn.run.run_id not in orch._run_tasks)
        await eventually(lambda: len(summarizer.calls) == 1)
        assert old_text in summarizer.calls[0][0]

        if change == "reset":
            await orch.new_context(channel.channel_id)
            assert store.get_channel(channel.channel_id).rendered_chars_since_checkpoint == 0
        else:
            await orch.edit_message(channel.channel_id, original.seq, "corrected covered message")

        summarizer.resolve(0, "STALE SUMMARY MUST NOT COMMIT")
        await eventually(lambda: channel.channel_id not in orch._checkpoint_tasks)
        assert checkpoint_events(store, channel.channel_id) == []
        if change == "reset":
            assert store.get_channel(channel.channel_id).rendered_chars_since_checkpoint == 0
    finally:
        await orch.close()
        store.close()


@pytest.mark.asyncio
async def test_failed_summary_keeps_previous_checkpoint_and_counter(tmp_path):
    store = Store(tmp_path / "failure.sqlite3")
    runner_factory = ControlledFactory()
    summarizer = DeferredSummarizer()
    orch = Orchestrator(
        store,
        settings(tmp_path, checkpoint_threshold=80, checkpoint_tail_chars=30, checkpoint_summary_chars=128),
        FakeRouter(), runner_factory, lambda *_: True, human_id="local", summarizer=summarizer,
    )
    orch.put_agent(Agent("alpha", "alpha", "Alpha", "specialist", "codex", "", "help"))
    channel = orch.create_channel("failure", agent_ids=["alpha"])
    await orch.start()
    try:
        await start_and_finish(orch, runner_factory, channel, "OLD LOG " + ("old detail " * 20), "first answer")
        await eventually(lambda: len(summarizer.calls) == 1)
        summarizer.resolve(0, "PRESERVED PREVIOUS SUMMARY")
        await eventually(lambda: len(checkpoint_events(store, channel.channel_id)) == 1)
        previous = checkpoint_events(store, channel.channel_id)[0]

        await orch.send_message(channel.channel_id, "NEW LOG " + ("new detail " * 20), ["alpha"])
        await eventually(lambda: len(runner_factory.started) == 2)
        second_runner = runner_factory.started[1]
        second_runner.finish("second answer")
        await eventually(lambda: second_runner.turn.run.run_id not in orch._run_tasks)
        await eventually(lambda: len(summarizer.calls) == 2)
        counter_before_failure = store.get_channel(channel.channel_id).rendered_chars_since_checkpoint
        summarizer.fail(1, RuntimeError("injected summarizer failure"))
        await eventually(lambda: channel.channel_id not in orch._checkpoint_tasks)

        remaining = checkpoint_events(store, channel.channel_id)
        assert len(remaining) == 1
        assert remaining[0].id == previous.id
        assert remaining[0].payload["summary"] == "PRESERVED PREVIOUS SUMMARY"
        assert store.get_channel(channel.channel_id).rendered_chars_since_checkpoint == counter_before_failure
    finally:
        await orch.close()
        store.close()


@pytest.mark.asyncio
async def test_raw_tool_result_does_not_increase_rendered_checkpoint_counter(tmp_path):
    store = Store(tmp_path / "tool-result.sqlite3")
    runner_factory = ControlledFactory()
    summarizer = DeferredSummarizer()
    orch = Orchestrator(
        store,
        settings(tmp_path, checkpoint_threshold=200, checkpoint_tail_chars=30, checkpoint_summary_chars=128),
        FakeRouter(), runner_factory, lambda *_: True, human_id="local", summarizer=summarizer,
    )
    orch.put_agent(Agent("alpha", "alpha", "Alpha", "specialist", "codex", "", "help"))
    channel = orch.create_channel("tool output", agent_ids=["alpha"])
    await orch.start()
    try:
        await orch.send_message(channel.channel_id, "small request", ["alpha"])
        await eventually(lambda: len(runner_factory.started) == 1)
        runner = runner_factory.started[0]
        await eventually(lambda: store.get_run(runner.turn.run.run_id).status == "running")
        before = store.get_channel(channel.channel_id).rendered_chars_since_checkpoint
        runner.emit(
            "tool_result", tool_call_id="tool-1", output="RAW TOOL CONTENT " * 1000,
            is_error=False, bytes=17000,
        )
        await eventually(lambda: any(e.kind == "tool_result" for e in store.events(channel.channel_id)))
        after = store.get_channel(channel.channel_id).rendered_chars_since_checkpoint
        assert after == before
        runner.finish("done")
        await eventually(lambda: runner.turn.run.run_id not in orch._run_tasks)
        assert not summarizer.calls
    finally:
        await orch.close()
        store.close()
