from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from lgt.models import Agent, Attachment, Channel, Run, WorkspaceError
from lgt.store import Store


def agent(id: str) -> Agent:
    return Agent(id, id, id, "description", "codex", "default", "prompt",
                 created_at="2026-01-01T00:00:00+00:00")


@pytest.fixture
def store(tmp_path):
    db = Store(tmp_path / "test.db")
    db.put_agent(agent("a"))
    db.create_channel(Channel("c", "channel", "General", str(tmp_path), False),
                      [("human", "h"), ("agent", "a")])
    yield db
    db.close()


def test_agent_identity_lifecycle_and_dm(store):
    first = store.get_agent("a")
    assert first.hue == 0
    assert first.avatar == {"style": "critters", "seed": "a"}
    store.put_agent(replace(first, name="Renamed", hue=7, created_at="later"))
    updated = store.get_agent("a")
    assert (updated.hue, updated.created_at, updated.avatar) == (0, first.created_at, first.avatar)
    store.create_channel(Channel("dm", "dm", "a", store.get_channel("c").cwd, False),
                         [("human", "h"), ("agent", "a")])
    store.set_agent_dm_channel("a", "dm")
    assert store.get_agent("a").dm_channel_id == "dm"
    store.retire_agent("a")
    assert store.list_agents() == []
    assert len(store.list_agents(include_retired=True)) == 1
    store.put_agent(agent("b"))
    assert store.get_agent("b").hue == 1


def test_default_bottts_avatars_move_to_critters_once(tmp_path):
    db = Store(tmp_path / "old.db")
    db.put_agent(replace(agent("old"), avatar={"style": "bottts", "seed": "old"}))
    db.put_agent(replace(agent("lorelei"), avatar={"style": "lorelei", "seed": "x"}))
    db.conn.execute("PRAGMA user_version = 0")  # a database from before the change
    db.close()
    db = Store(tmp_path / "old.db")
    assert db.get_agent("old").avatar == {"style": "critters", "seed": "old"}
    assert db.get_agent("lorelei").avatar == {"style": "lorelei", "seed": "x"}
    # Later opens leave a deliberately chosen bottts avatar alone.
    db.put_agent(replace(db.get_agent("old"), avatar={"style": "bottts", "seed": "old"}))
    db.close()
    db = Store(tmp_path / "old.db")
    assert db.get_agent("old").avatar["style"] == "bottts"
    db.close()


def test_summaries_read_cursor_edits_search_and_reopen(store):
    human = store.append_event("c", "message", "human", "h", {"text": "hello"})
    agent_message = store.append_event("c", "message", "agent", "a", {"text": "old answer"},
                                       chain_id=human.chain_id)
    store.append_event("c", "tool_call", "agent", "a", {"summary": "Read app.py"},
                       chain_id=human.chain_id)
    store.append_event("c", "message_edit", "human", "h",
                       {"target_seq": agent_message.seq, "text": "new answer"}, chain_id=human.chain_id)
    summary = store.channel_summary("c", "h")
    assert summary["preview"]["text_excerpt"] == "Read app.py"
    assert summary["unread_count"] == 1
    assert store.search("old answer")["messages"] == []
    assert store.search("new answer")["messages"][0]["seq"] == agent_message.seq
    assert store.search("Read", kinds=["tool_call"])["messages"][0]["seq"] == 3
    assert store.set_read_cursor("c", "h", 2) == 2
    assert store.set_read_cursor("c", "h", 1) == 2
    assert store.channel_summary("c", "h")["unread_count"] == 0
    with pytest.raises(WorkspaceError):
        store.set_read_cursor("c", "h", 10)
    with pytest.raises(WorkspaceError):
        store.set_read_cursor("c", "h", True)
    store.append_event("c", "message_edit", "human", "h",
                       {"target_seq": agent_message.seq, "deleted": True}, chain_id=human.chain_id)
    assert store.search("new answer")["messages"] == []
    assert store.channel_summary("c", "h")["unread_count"] == 0
    store.append_event("c", "message_edit", "human", "h",
                       {"target_seq": agent_message.seq, "deleted": False}, chain_id=human.chain_id)
    assert store.search("new answer")["messages"][0]["seq"] == agent_message.seq
    assert store.channel_summary("c", "h")["unread_count"] == 0
    assert len(store.list_channel_summaries("h")) == 1
    path = store.conn.execute("PRAGMA database_list").fetchone()["file"]
    store.close()
    reopened = Store(path)
    assert reopened.search("new answer")["messages"]
    assert reopened.search("Read")["messages"]
    assert reopened.set_read_cursor("c", "h", 1) == 2
    # Fixture tearDown closes the original connection a second time harmlessly.
    reopened.close()


def test_run_filters_usage_limits_profile_and_attachment_quota(store):
    root = store.append_event("c", "message", "human", "h", {"text": "run"})
    run = Run("r", "c", "a", root.seq, 1, 1, "cold", "codex", "C:/workspace",
              tokens_in=10, tokens_out=5, tokens_cached_in=3, tokens_total=15,
              started_at="2026-01-01T00:00:00+00:00")
    assert store.create_run(run)
    assert len(store.list_runs(agent_id="a", status="active", limit=1)) == 1
    store.update_run("r", status="completed", error={"code": "harness", "message": "failed"})
    assert store.get_run("r").error == {"code": "harness", "message": "failed"}
    assert len(store.list_runs(status="terminal")) == 1
    assert store.usage("agent")[0]["tokens_total"] == 15
    assert store.usage("day", since="2027-01-01") == []
    assert store.usage("day", since="2026-01-01")[0]["day"] == "2026-01-01"
    assert store.usage("day", since="2025-12-31T19:00:00-05:00")[0]["tokens_total"] == 15
    with pytest.raises(WorkspaceError):
        store.usage("day", since="not-a-date")
    second = store.append_event("c", "message", "human", "h", {"text": "again"})
    assert store.create_run(replace(run, run_id="r2", trigger_seq=second.seq,
                                    started_at="2026-01-02T00:00:00+00:00"))
    assert [r.run_id for r in store.list_runs(limit=1)] == ["r"]
    assert [r.run_id for r in store.list_runs(limit=1, newest_first=True)] == ["r2"]
    queued_message = store.append_event("c", "message", "human", "h", {"text": "queued"})
    assert store.create_run(replace(run, run_id="queued", trigger_seq=queued_message.seq,
                                    started_at=None, tokens_in=0, tokens_out=0,
                                    tokens_cached_in=0, tokens_total=0))
    assert all(row["day"] is not None for row in store.usage("day"))
    assert len(store.usage("day")) == 2
    assert store.get_harness_limits("codex") is None
    store.put_harness_limits("codex", {"primary": {"usedPercent": 10}})
    assert store.get_harness_limits("codex")["primary"]["usedPercent"] == 10
    assert store.set_human_profile("h", "Ada")["display_name"] == "Ada"
    assert store.get_human_profile("h")["display_name"] == "Ada"
    store.put_attachment(Attachment("att", "c", "a", "text/plain", 8, "hash", "path",
                                    created_at="2026-01-01T00:00:00+00:00"))
    assert store.attachment_channel_bytes("c") == 8
    assert len(store.expired_unsent_attachments("2026-02-01")) == 1


def test_additive_migration_from_legacy_agent_table(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE agents (
        agent_id TEXT PRIMARY KEY, handle TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
        description TEXT NOT NULL, harness TEXT NOT NULL, model TEXT NOT NULL,
        system_prompt TEXT NOT NULL, allowed_tools TEXT NOT NULL DEFAULT '[]',
        default_cwd TEXT, permission_mode TEXT NOT NULL DEFAULT 'bypass',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    connection.execute("""INSERT INTO agents VALUES
        ('legacy', 'legacy', 'Legacy', '', 'codex', 'default', '', '[]', NULL,
         'bypass', '2025-01-01', '2025-01-01')""")
    connection.execute("""CREATE TABLE runs (
        run_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, agent_id TEXT NOT NULL,
        trigger_seq INTEGER NOT NULL, delta_start_seq INTEGER NOT NULL,
        delta_end_seq INTEGER NOT NULL, session_mode TEXT NOT NULL, harness TEXT NOT NULL,
        harness_session_id TEXT, cwd TEXT NOT NULL, pgid INTEGER, status TEXT NOT NULL,
        error TEXT, exit_code INTEGER, started_at TEXT, ended_at TEXT,
        tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0)""")
    connection.execute("""INSERT INTO runs VALUES
        ('old-run', 'old-channel', 'legacy', 1, 1, 1, 'cold', 'codex', NULL, '/tmp',
         NULL, 'completed', NULL, NULL, '2025-01-01', '2025-01-01', 7, 3, 0.1)""")
    connection.execute("""INSERT INTO runs VALUES
        ('old-failed', 'old-channel', 'legacy', 2, 2, 2, 'cold', 'codex', NULL, '/tmp',
         NULL, 'failed', 'out of memory', 137,
         '2025-01-01T00:00:00+00:00', '2025-01-01T00:01:00+00:00', 0, 0, 0)""")
    connection.execute("""INSERT INTO runs VALUES
        ('old-cancelled', 'old-channel', 'legacy', 3, 3, 3, 'cold', 'codex', NULL, '/tmp',
         NULL, 'cancelled', 'cancelled by user', NULL, NULL, NULL, 0, 0, 0)""")
    connection.commit()
    connection.close()
    store = Store(path)
    assert store.get_agent("legacy").hue == 0
    assert store.get_agent("legacy").avatar["seed"] == "legacy"
    assert store.get_run("old-run").tokens_in == 7
    assert store.get_run("old-run").tokens_cached_in == 0
    assert store.get_run("old-run").tokens_total == 10
    assert store.get_run("old-run").duration_ms == 0
    failure = store.get_run("old-failed")
    assert failure.error["code"] == "oom"
    assert failure.error["exit_code"] == 137
    assert failure.duration_ms == 60000
    assert store.get_run("old-cancelled").error["code"] == "cancelled"
    persisted = store.conn.execute(
        "SELECT error, duration_ms FROM runs WHERE run_id = 'old-failed'"
    ).fetchone()
    store.close()
    reopened = Store(path)
    assert reopened.get_agent("legacy").hue == 0
    assert reopened.get_run("old-run").tokens_total == 10
    assert reopened.get_run("old-failed").error["code"] == "oom"
    assert tuple(reopened.conn.execute(
        "SELECT error, duration_ms FROM runs WHERE run_id = 'old-failed'"
    ).fetchone()) == tuple(persisted)
    reopened.close()
