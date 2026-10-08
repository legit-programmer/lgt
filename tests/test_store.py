from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from lgt.models import Agent, Attachment, Channel, Run, Session, WorkspaceError
from lgt.store import Store


def make_agent(agent_id: str = "agent-a", **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_id": agent_id,
        "handle": agent_id,
        "name": "Agent A",
        "description": "A test agent",
        "harness": "claude_code",
        "model": "haiku",
        "system_prompt": "Be helpful",
        "allowed_tools": ["Read", "Write"],
        "default_cwd": None,
        "permission_mode": "bypass",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def make_channel(channel_id: str = "channel-a", **overrides: object) -> Channel:
    values: dict[str, object] = {
        "channel_id": channel_id,
        "kind": "channel",
        "name": "Test",
        "cwd": "C:/workspace",
        "cwd_managed": False,
        "next_seq": 1,
        "rendered_chars_since_checkpoint": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "archived_at": None,
    }
    values.update(overrides)
    return Channel(**values)  # type: ignore[arg-type]


def make_run(run_id: str, *, trigger_seq: int = 1, status: str = "queued") -> Run:
    return Run(
        run_id=run_id, channel_id="channel-a", agent_id="agent-a",
        trigger_seq=trigger_seq, delta_start_seq=1, delta_end_seq=trigger_seq,
        session_mode="cold", harness="claude_code", cwd="C:/workspace", status=status,
    )


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "workspace.sqlite3"
        self.store = Store(self.db_path)
        self.store.put_agent(make_agent())
        self.store.create_channel(make_channel(), [("human", "human-a"), ("agent", "agent-a")])

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def test_json_round_trip_and_human_event_starts_its_chain(self) -> None:
        agent = make_agent(allowed_tools=["Read", "Write", "Search"])
        self.store.put_agent(agent)
        loaded = self.store.get_agent(agent.agent_id)
        self.assertEqual(loaded.allowed_tools, ["Read", "Write", "Search"])
        self.assertEqual(self.store.list_agents(), [loaded])

        event = self.store.append_event(
            "channel-a", "message", "human", "human-a",
            {"text": "hello", "mentions": ["agent-a"], "is_test": True},
            rendered_chars=5,
        )
        self.assertEqual(event.chain_id, event.id)
        self.assertEqual(event.seq, 1)
        self.assertEqual(event.payload, {"text": "hello", "mentions": ["agent-a"], "is_test": True})
        self.assertEqual(self.store.get_channel("channel-a").next_seq, 2)
        self.assertEqual(self.store.get_channel("channel-a").rendered_chars_since_checkpoint, 5)

    def test_events_are_append_only_and_nonhuman_roots_need_a_chain(self) -> None:
        event = self.store.append_event("channel-a", "message", "human", "human-a", {"text": "root"})
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute("UPDATE events SET payload = '{}' WHERE id = ?", (event.id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute("DELETE FROM events WHERE id = ?", (event.id,))
        with self.assertRaises(WorkspaceError):
            self.store.append_event("channel-a", "system", "system", "system", {"text": "orphan"})
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_event(
                "channel-a", "system", "system", "system", {"text": "missing chain"}, chain_id=999,
            )
        self.assertEqual(len(self.store.events("channel-a")), 1)
        self.assertEqual(self.store.get_channel("channel-a").next_seq, 2)

    def test_nested_transactions_and_outer_rollback(self) -> None:
        with self.store.transaction():
            first = self.store.append_event("channel-a", "message", "human", "human-a", {"text": "one"})
            with self.assertRaises(RuntimeError):
                with self.store.transaction():
                    self.store.append_event(
                        "channel-a", "message", "human", "human-a", {"text": "rolled back"},
                    )
                    raise RuntimeError("rollback savepoint")
            last = self.store.append_event("channel-a", "message", "human", "human-a", {"text": "two"})
        self.assertEqual([event.seq for event in self.store.events("channel-a")], [1, 2])
        self.assertLess(first.id, last.id)
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.append_event("channel-a", "message", "human", "human-a", {"text": "gone"})
                raise RuntimeError("rollback transaction")
        self.assertEqual([event.seq for event in self.store.events("channel-a")], [1, 2])
        self.assertEqual(self.store.get_channel("channel-a").next_seq, 3)

    def test_sequences_and_global_replay_cursor(self) -> None:
        self.store.create_channel(make_channel("channel-b"), [("human", "human-a")])
        a1 = self.store.append_event("channel-a", "message", "human", "human-a", {"text": "a1"})
        b1 = self.store.append_event("channel-b", "message", "human", "human-a", {"text": "b1"})
        a2 = self.store.append_event(
            "channel-a", "message", "human", "human-a", {"text": "a2"}, chain_id=a1.chain_id,
        )
        self.assertEqual([event.seq for event in self.store.events("channel-a")], [1, 2])
        self.assertEqual([event.seq for event in self.store.events("channel-a", from_seq=2, to_seq=2)], [2])
        self.assertEqual([event.id for event in self.store.replay(0, ["channel-a", "channel-b"], 10)],
                         [a1.id, b1.id, a2.id])
        self.assertEqual([event.id for event in self.store.replay(a1.id, ["channel-a", "channel-b"], 1)],
                         [b1.id])

    def test_scrollback_pages_are_nearest_first_and_have_exclusive_boundaries(self) -> None:
        root = None
        for number in range(1, 11):
            event = self.store.append_event(
                "channel-a", "message", "human", "human-a", {"text": f"message {number}"},
                chain_id=root,
            )
            root = event.chain_id

        latest = self.store.scrollback("channel-a", limit=4)
        preceding = self.store.scrollback("channel-a", before_seq=latest[0].seq, limit=4)
        oldest = self.store.scrollback("channel-a", before_seq=preceding[0].seq, limit=4)
        self.assertEqual([event.seq for event in latest], [7, 8, 9, 10])
        self.assertEqual([event.seq for event in preceding], [3, 4, 5, 6])
        self.assertEqual([event.seq for event in oldest], [1, 2])
        self.assertEqual([event.seq for event in oldest + preceding + latest], list(range(1, 11)))
        self.assertEqual(
            [event.seq for event in self.store.scrollback("channel-a", after_seq=3, limit=3)],
            [4, 5, 6],
        )
        self.assertEqual(
            [event.seq for event in self.store.scrollback("channel-a", after_seq=3, before_seq=9)],
            [4, 5, 6, 7, 8],
        )

    def test_channel_cwd_can_move_and_records_managed_state(self) -> None:
        self.store.set_channel_cwd("channel-a", "C:/different", False)
        channel = self.store.get_channel("channel-a")
        self.assertEqual((channel.cwd, channel.cwd_managed), ("C:/different", False))
        with self.assertRaises(KeyError):
            self.store.set_channel_cwd("missing", "C:/x", True)

    def test_sent_attachment_cannot_be_rebound_or_deleted(self) -> None:
        event = self.store.append_event("channel-a", "message", "human", "human-a", {"text": "file"})
        self.store.put_attachment(Attachment("att-1", "channel-a", "a.txt", "text/plain", 1, "x", "C:/a.txt"))
        self.store.bind_attachment("att-1", event.seq)
        with self.assertRaises(WorkspaceError):
            self.store.bind_attachment("att-1", event.seq)
        with self.assertRaises(WorkspaceError):
            self.store.delete_attachment("att-1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute("DELETE FROM attachments WHERE attachment_id = 'att-1'")
        self.assertEqual(self.store.message_attachments("channel-a", [event.seq])[0].message_seq, event.seq)

    def test_queue_survives_reopen_and_can_clear_agent_id(self) -> None:
        event = self.store.append_event("channel-a", "message", "human", "human-a", {"text": "queued"})
        item = self.store.enqueue("channel-a", event.seq, "agent-a", ["run-1"], state="awaiting_agent")
        self.store.update_queue(item.queue_id, agent_id=None, wait_for=[])
        self.store.close()
        self.store = Store(self.db_path)
        queued = self.store.queue(channel_id="channel-a", state="awaiting_agent")
        self.assertEqual(len(queued), 1)
        self.assertIsNone(queued[0].agent_id)
        self.assertEqual(queued[0].wait_for, [])

    def test_run_insert_is_idempotent_and_active_filter_observes_terminal_states(self) -> None:
        first = self.store.append_event("channel-a", "message", "human", "human-a", {"text": "go"})
        run = make_run("run-1", trigger_seq=first.seq)
        self.assertTrue(self.store.create_run(run))
        self.assertFalse(self.store.create_run(make_run("run-duplicate", trigger_seq=first.seq)))
        self.assertEqual(self.store.get_run("run-1"), run)
        self.assertEqual(self.store.list_runs(active_only=True), [run])

        for status in ("starting", "running"):
            self.store.append_event(
                "channel-a", "run_status", "system", "system",
                {"run_id": "run-1", "status": status},
                run_id="run-1", chain_id=first.chain_id,
            )
        self.store.update_run("run-1", status="completed", ended_at="2026-01-01T00:01:00+00:00")
        terminal = self.store.append_event(
            "channel-a", "run_status", "system", "system", {"run_id": "run-1", "status": "completed"},
            run_id="run-1", chain_id=first.chain_id,
        )
        self.assertEqual(terminal.payload["status"], "completed")
        self.assertEqual(self.store.list_runs(active_only=True), [])
        self.assertEqual(self.store.list_runs()[0].status, "completed")

        for index, status in enumerate(("failed", "cancelled"), start=2):
            next_run = make_run(f"run-{index}", trigger_seq=index)
            self.assertTrue(self.store.create_run(next_run))
            self.store.update_run(next_run.run_id, status=status)
            self.store.append_event(
                "channel-a", "run_status", "system", "system",
                {"run_id": next_run.run_id, "status": status},
                run_id=next_run.run_id, chain_id=first.chain_id,
            )
        self.assertEqual(self.store.list_runs(active_only=True), [])
        self.assertEqual(
            {run.status for run in self.store.list_runs()},
            {"completed", "failed", "cancelled"},
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_event(
                "channel-a", "run_status", "system", "system", {"run_id": "run-1", "status": "failed"},
                run_id="run-1", chain_id=first.chain_id,
            )

    def test_reopen_migrates_status_index_to_terminal_events_only(self) -> None:
        root = self.store.append_event("channel-a", "message", "human", "human-a", {"text": "go"})
        self.assertTrue(self.store.create_run(make_run("run-migrate", trigger_seq=root.seq)))
        self.store.conn.execute("DROP INDEX events_one_run_status_idx")
        self.store.conn.execute(
            "CREATE UNIQUE INDEX events_one_run_status_idx ON events(run_id) "
            "WHERE kind = 'run_status' AND run_id IS NOT NULL"
        )
        self.store.close()
        self.store = Store(self.db_path)

        for status in ("starting", "running", "completed"):
            self.store.append_event(
                "channel-a", "run_status", "system", "system",
                {"run_id": "run-migrate", "status": status},
                run_id="run-migrate", chain_id=root.chain_id,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_event(
                "channel-a", "run_status", "system", "system",
                {"run_id": "run-migrate", "status": "cancelled"},
                run_id="run-migrate", chain_id=root.chain_id,
            )

    def test_sessions_preserve_clean_and_dirty_status(self) -> None:
        session = Session(
            agent_id="agent-a", channel_id="channel-a", harness="claude_code",
            harness_session_id="harness-session", cwd="C:/workspace", last_seen_seq=3,
            config_fingerprint="abc", last_run_status="clean",
            last_used_at="2026-01-01T00:00:00+00:00",
        )
        self.assertIsNone(self.store.get_session("agent-a", "channel-a"))
        self.store.put_session(session)
        self.assertEqual(self.store.get_session("agent-a", "channel-a"), session)
        dirty = Session(**{**session.__dict__, "last_run_status": "dirty"})
        self.store.put_session(dirty)
        self.assertEqual(self.store.get_session("agent-a", "channel-a").last_run_status, "dirty")

    def test_channel_and_member_creation_roll_back_together(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_channel(make_channel("channel-invalid"), [("agent", "missing-agent")])
        with self.assertRaises(KeyError):
            self.store.get_channel("channel-invalid")


if __name__ == "__main__":
    unittest.main()
