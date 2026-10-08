from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lgt.context import render_delta, render_turn, resolve_session
from lgt.models import Agent, Channel, Session
from lgt.store import Store


class ContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tempdir.name) / "context.sqlite3")
        self.agent = Agent(
            agent_id="agent-a", handle="alpha", name="Alpha", description="Primary test agent",
            harness="claude_code", model="haiku", system_prompt="Be useful",
            allowed_tools=["Read", "Write"], default_cwd=None,
            created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        )
        self.other_agent = Agent(
            agent_id="agent-b", handle="beta", name="Beta", description="Second test agent",
            harness="codex", model="gpt-test", system_prompt="Help too",
            allowed_tools=["Read"], default_cwd=None,
            created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        )
        self.store.put_agent(self.agent)
        self.store.put_agent(self.other_agent)
        self.channel = Channel(
            channel_id="channel-a", kind="channel", name="Test", cwd="C:/workspace",
            cwd_managed=False, created_at="2026-01-01T00:00:00+00:00",
        )
        self.store.create_channel(self.channel, [("human", "human-a"), ("agent", "agent-a"), ("agent", "agent-b")])
        self.chain_id: int | None = None

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def add(self, kind: str, author_kind: str, author_id: str, payload: dict, **kwargs):
        chain_id = kwargs.pop("chain_id", self.chain_id)
        event = self.store.append_event(
            self.channel.channel_id, kind, author_kind, author_id, payload,
            chain_id=chain_id, **kwargs,
        )
        if self.chain_id is None:
            self.chain_id = event.chain_id
        return event

    def add_human_message(self, text: str):
        return self.add("message", "human", "human-a", {"text": text, "mentions": []})

    def make_session(self, **changes: object) -> Session:
        now = datetime.now(timezone.utc)
        session = Session(
            agent_id=self.agent.agent_id, channel_id=self.channel.channel_id,
            harness=self.agent.harness, harness_session_id="harness-session",
            cwd=self.channel.cwd, last_seen_seq=0,
            config_fingerprint=self.agent.fingerprint(), last_run_status="clean",
            last_used_at=(now - timedelta(seconds=10)).isoformat(),
        )
        return replace(session, **changes)

    def resolve(self, end_seq: int, *, artifact_exists=lambda _session_id, _cwd: True,
                ttl_seconds: float | None = 3600):
        return resolve_session(
            self.store, self.agent, self.channel, end_seq, artifact_exists, ttl_seconds,
        )

    def test_rendering_is_deterministic_and_filters_own_resume_context(self) -> None:
        self.add_human_message("question")
        self.add("message", "agent", "agent-a", {"text": "my earlier answer"})
        self.add("message", "agent", "agent-b", {"text": "peer reply"})
        for name in ("Read", "Read", "Search"):
            self.add("tool_call", "agent", "agent-a", {"tool_call_id": name, "name": name, "input": {}})
        self.add("tool_call", "agent", "agent-b", {"tool_call_id": "grep-1", "name": "Grep", "input": {}})
        self.add("tool_result", "agent", "agent-a", {"tool_call_id": "Read", "output": "SECRET TOOL OUTPUT"})
        self.add("tool_result", "agent", "agent-b", {"tool_call_id": "grep-1", "output": "ANOTHER SECRET"})
        end_seq = self.store.get_channel(self.channel.channel_id).next_seq - 1

        cold = render_delta(self.store, "agent-a", "channel-a", 1, end_seq, "cold")
        resumed = render_delta(self.store, "agent-a", "channel-a", 1, end_seq, "resume")
        self.assertEqual(cold, render_delta(self.store, "agent-a", "channel-a", 1, end_seq, "cold"))
        self.assertEqual(resumed, render_delta(self.store, "agent-a", "channel-a", 1, end_seq, "resume"))
        self.assertIn("[alpha] my earlier answer", cold)
        self.assertIn("[beta] peer reply", cold)
        self.assertIn("[alpha] (ran 3 tools: Read x2, Search)", cold)
        self.assertIn("[beta] (ran 1 tools: Grep)", cold)
        self.assertNotIn("my earlier answer", resumed)
        self.assertNotIn("(ran 3 tools: Read x2, Search)", resumed)
        self.assertIn("[beta] (ran 1 tools: Grep)", resumed)
        for raw_output in ("SECRET TOOL OUTPUT", "ANOTHER SECRET"):
            self.assertNotIn(raw_output, cold)
            self.assertNotIn(raw_output, resumed)

    def test_edits_and_deletions_are_applied_as_of_the_bounded_end_sequence(self) -> None:
        original = self.add_human_message("before edit")
        first_edit = self.add(
            "message_edit", "human", "human-a", {"target_seq": original.seq, "text": "first edit"},
        )
        later_edit = self.add(
            "message_edit", "human", "human-a", {"target_seq": original.seq, "text": "future edit"},
        )
        deletion = self.add(
            "message_edit", "human", "human-a", {"target_seq": original.seq, "deleted": True},
        )

        at_first_edit = render_delta(self.store, "agent-a", "channel-a", 1, first_edit.seq, "cold")
        at_later_edit = render_delta(self.store, "agent-a", "channel-a", 1, later_edit.seq, "cold")
        at_deletion = render_delta(self.store, "agent-a", "channel-a", 1, deletion.seq, "cold")
        self.assertIn("first edit", at_first_edit)
        self.assertNotIn("future edit", at_first_edit)
        self.assertIn("future edit", at_later_edit)
        self.assertNotIn("before edit", at_later_edit)
        self.assertNotIn("future edit", at_deletion)
        self.assertNotIn("[human-a]", at_deletion)

    def test_clean_session_validity_checks_fingerprint_cwd_artifact_and_ttl(self) -> None:
        clean_session = self.make_session()
        self.store.put_session(clean_session)
        valid = self.resolve(0)
        self.assertEqual((valid.mode, valid.start_seq, valid.session), ("resume", 1, clean_session))

        invalid_sessions = {
            "dirty": self.make_session(last_run_status="dirty"),
            "fingerprint": self.make_session(config_fingerprint="stale"),
            "cwd": self.make_session(cwd="C:/other"),
            "expired": self.make_session(last_used_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()),
        }
        for reason, session in invalid_sessions.items():
            with self.subTest(reason=reason):
                self.store.put_session(session)
                plan = self.resolve(0, ttl_seconds=60)
                self.assertEqual((plan.mode, plan.start_seq, plan.session), ("cold", 1, None))

        self.store.put_session(self.make_session())
        missing_artifact = self.resolve(
            0, artifact_exists=lambda _session_id, _cwd: False, ttl_seconds=None,
        )
        self.assertEqual((missing_artifact.mode, missing_artifact.start_seq), ("cold", 1))
        self.assertIsNone(missing_artifact.summary)

    def test_context_reset_forces_cold_start_after_reset(self) -> None:
        first = self.add_human_message("before reset")
        self.store.put_session(self.make_session(last_seen_seq=first.seq))
        reset = self.add("context_reset", "human", "human-a", {})
        plan = self.resolve(reset.seq)
        self.assertEqual((plan.mode, plan.start_seq), ("cold", reset.seq + 1))
        self.assertIsNone(plan.session)

    def test_checkpoint_starts_after_covers_through_seq_not_checkpoint_event(self) -> None:
        self.add_human_message("summarized exchange")
        second = self.add_human_message("raw exchange one")
        self.add_human_message("raw exchange two")
        checkpoint = self.add(
            "context_checkpoint", "system", "system",
            {"covers_through_seq": 1, "summary": "summary through first exchange"},
        )

        plan = self.resolve(checkpoint.seq)
        self.assertEqual((plan.mode, plan.start_seq), ("cold", 2))
        self.assertEqual(plan.summary, "summary through first exchange")
        rendered = render_turn(self.store, self.agent, self.channel, plan, checkpoint.seq)
        self.assertIn("<context_checkpoint>\nsummary through first exchange\n</context_checkpoint>", rendered)
        self.assertIn("raw exchange one", rendered)
        self.assertNotIn("summarized exchange", rendered)
        self.assertLess(second.seq, checkpoint.seq)

    def test_checkpoint_before_reset_is_ignored_and_edit_after_checkpoint_invalidates_it(self) -> None:
        self.add_human_message("old context")
        self.add(
            "context_checkpoint", "system", "system",
            {"covers_through_seq": 1, "summary": "stale summary"},
        )
        reset = self.add("context_reset", "human", "human-a", {})
        after_reset = self.add_human_message("new context")
        post_reset_checkpoint = self.add(
            "context_checkpoint", "system", "system",
            {"covers_through_seq": after_reset.seq, "summary": "new summary"},
        )
        plan = self.resolve(post_reset_checkpoint.seq)
        self.assertEqual(plan.start_seq, after_reset.seq + 1)
        self.assertEqual(plan.summary, "new summary")

        self.add(
            "message_edit", "human", "human-a",
            {"target_seq": after_reset.seq, "text": "corrected new context"},
        )
        invalidated = self.resolve(self.store.get_channel("channel-a").next_seq - 1)
        self.assertEqual((invalidated.mode, invalidated.start_seq), ("cold", reset.seq + 1))
        self.assertIsNone(invalidated.summary)


if __name__ == "__main__":
    unittest.main()
