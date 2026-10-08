"""SQLite persistence for the multi-agent workspace."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import (
    Agent, Attachment, Channel, Event, QueueItem, Run, Session, WorkspaceError, utc_now,
)
from .run_errors import duration_ms as calculate_duration_ms, normalize_error


_UNSET = object()
_RUN_UPDATE_FIELDS = frozenset({
    "trigger_seq", "delta_start_seq", "delta_end_seq", "session_mode", "harness",
    "harness_session_id", "cwd", "pgid", "status", "error", "exit_code",
    "started_at", "ended_at", "duration_ms", "tokens_in", "tokens_out",
    "tokens_cached_in", "tokens_cache_creation", "tokens_reasoning", "tokens_total",
    "model_context_window", "context_tokens",
})


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str) -> Any:
    return json.loads(value)


def _error(value: str | None) -> dict[str, Any] | str | None:
    if value is None:
        return None
    if not value.startswith("{"):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else value
    except (ValueError, TypeError):
        return value


def _agent(row: sqlite3.Row) -> Agent:
    return Agent(
        agent_id=row["agent_id"], handle=row["handle"], name=row["name"],
        description=row["description"], harness=row["harness"], model=row["model"],
        system_prompt=row["system_prompt"], allowed_tools=_load(row["allowed_tools"]),
        default_cwd=row["default_cwd"], permission_mode=row["permission_mode"],
        avatar=_load(row["avatar"]), hue=row["hue"],
        extra_args=_load(row["extra_args"]), command=_load(row["command"]),
        retired_at=row["retired_at"], dm_channel_id=row["dm_channel_id"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _channel(row: sqlite3.Row) -> Channel:
    return Channel(
        channel_id=row["channel_id"], kind=row["kind"], name=row["name"], cwd=row["cwd"],
        cwd_managed=bool(row["cwd_managed"]), next_seq=row["next_seq"],
        rendered_chars_since_checkpoint=row["rendered_chars_since_checkpoint"],
        created_at=row["created_at"], archived_at=row["archived_at"],
    )


def _event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"], channel_id=row["channel_id"], seq=row["seq"], ts=row["ts"],
        kind=row["kind"], author_kind=row["author_kind"], author_id=row["author_id"],
        run_id=row["run_id"], chain_id=row["chain_id"], hop=row["hop"],
        payload=_load(row["payload"]),
    )


def _run(row: sqlite3.Row) -> Run:
    error = _error(row["error"])
    if row["status"] in {"failed", "cancelled"}:
        error = normalize_error(error, row["exit_code"])
    elapsed = row["duration_ms"]
    if elapsed is None and row["started_at"] and row["ended_at"]:
        try:
            elapsed = calculate_duration_ms(row["started_at"], row["ended_at"])
        except (ValueError, TypeError):
            pass
    return Run(
        run_id=row["run_id"], channel_id=row["channel_id"], agent_id=row["agent_id"],
        trigger_seq=row["trigger_seq"], delta_start_seq=row["delta_start_seq"],
        delta_end_seq=row["delta_end_seq"], session_mode=row["session_mode"],
        harness=row["harness"], cwd=row["cwd"],
        harness_session_id=row["harness_session_id"], pgid=row["pgid"],
        status=row["status"], error=error, exit_code=row["exit_code"],
        started_at=row["started_at"], ended_at=row["ended_at"],
        duration_ms=elapsed, tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"], tokens_cached_in=row["tokens_cached_in"],
        tokens_cache_creation=row["tokens_cache_creation"],
        tokens_reasoning=row["tokens_reasoning"], tokens_total=row["tokens_total"],
        model_context_window=row["model_context_window"], context_tokens=row["context_tokens"],
    )


def _session(row: sqlite3.Row) -> Session:
    return Session(
        agent_id=row["agent_id"], channel_id=row["channel_id"], harness=row["harness"],
        harness_session_id=row["harness_session_id"], cwd=row["cwd"],
        last_seen_seq=row["last_seen_seq"], config_fingerprint=row["config_fingerprint"],
        last_run_status=row["last_run_status"], last_used_at=row["last_used_at"],
    )


def _queue_item(row: sqlite3.Row) -> QueueItem:
    return QueueItem(
        queue_id=row["queue_id"], channel_id=row["channel_id"],
        event_seq=row["event_seq"], agent_id=row["agent_id"],
        wait_for=_load(row["wait_for"]), state=row["state"], created_at=row["created_at"],
    )


def _attachment(row: sqlite3.Row) -> Attachment:
    return Attachment(
        attachment_id=row["attachment_id"], channel_id=row["channel_id"],
        filename=row["filename"], media_type=row["media_type"],
        size_bytes=row["size_bytes"], sha256=row["sha256"], path=row["path"],
        message_seq=row["message_seq"], created_at=row["created_at"],
    )


class Store:
    """Synchronous SQLite event store.

    Mutating methods use transactions and safely compose inside an explicit
    ``transaction()`` block. Missing records raise ``KeyError``; invalid
    non-human root events without a chain raise ``WorkspaceError``.
    """

    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.conn.executescript(schema)
        self._savepoint_counter = 0
        self._migrate()

    def _migrate(self) -> None:
        """Add columns to databases created before the current schema."""
        additions = {
            "agents": {
                "avatar": "TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(avatar))",
                "hue": "INTEGER", "extra_args": "TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(extra_args))",
                "command": "TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(command))",
                "retired_at": "TEXT", "dm_channel_id": "TEXT REFERENCES channels(channel_id)",
            },
            "runs": {
                "duration_ms": "INTEGER", "tokens_cached_in": "INTEGER NOT NULL DEFAULT 0",
                "tokens_cache_creation": "INTEGER NOT NULL DEFAULT 0",
                "tokens_reasoning": "INTEGER NOT NULL DEFAULT 0",
                "tokens_total": "INTEGER NOT NULL DEFAULT 0", "model_context_window": "INTEGER",
                "context_tokens": "INTEGER",
            },
        }
        with self.transaction():
            for table, columns in additions.items():
                existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
                for column, declaration in columns.items():
                    if column not in existing:
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            self.conn.execute(
                """UPDATE runs SET tokens_total = tokens_in + tokens_out
                   WHERE tokens_total = 0 AND (tokens_in != 0 OR tokens_out != 0)"""
            )
            for row in self.conn.execute(
                """SELECT run_id, status, error, exit_code, started_at, ended_at,
                          duration_ms FROM runs
                   WHERE status IN ('failed', 'cancelled') OR
                         (duration_ms IS NULL AND started_at IS NOT NULL AND ended_at IS NOT NULL)"""
            ):
                updates: dict[str, Any] = {}
                if row["status"] in {"failed", "cancelled"}:
                    current = _error(row["error"])
                    normalized = normalize_error(current, row["exit_code"])
                    if current != normalized:
                        updates["error"] = _dump(normalized)
                if row["duration_ms"] is None and row["started_at"] and row["ended_at"]:
                    try:
                        updates["duration_ms"] = calculate_duration_ms(row["started_at"], row["ended_at"])
                    except (ValueError, TypeError):
                        pass
                if updates:
                    assignments = ", ".join(f"{column} = ?" for column in updates)
                    self.conn.execute(f"UPDATE runs SET {assignments} WHERE run_id = ?",
                                      (*updates.values(), row["run_id"]))
            rows = list(self.conn.execute("SELECT agent_id FROM agents WHERE hue IS NULL ORDER BY created_at, rowid"))
            count = self.conn.execute("SELECT count(*) FROM agents WHERE hue IS NOT NULL").fetchone()[0]
            for row in rows:
                self.conn.execute("UPDATE agents SET hue = ?, avatar = ? WHERE agent_id = ?",
                                  (count % 8, _dump({"style": "bottts", "seed": row["agent_id"]}), row["agent_id"]))
                count += 1
            has_search_index = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'search_fts'"
            ).fetchone() is not None
            if not has_search_index:
                self.conn.execute(
                    "CREATE VIRTUAL TABLE search_fts USING fts5(kind, channel_id UNINDEXED, seq UNINDEXED, text)"
                )
                self._rebuild_search()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Start an immediate transaction or a savepoint when nested."""
        if self.conn.in_transaction:
            self._savepoint_counter += 1
            savepoint = f"lgt_sp_{self._savepoint_counter}"
            self.conn.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except BaseException:
                self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            return

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except BaseException:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    def put_agent(self, agent: Agent) -> None:
        with self.transaction():
            existing = self.conn.execute("SELECT hue, created_at FROM agents WHERE agent_id = ?", (agent.agent_id,)).fetchone()
            hue = existing["hue"] if existing else self.conn.execute("SELECT count(*) FROM agents").fetchone()[0] % 8
            avatar = agent.avatar or {"style": "bottts", "seed": agent.agent_id}
            self.conn.execute(
                """INSERT INTO agents (
                       agent_id, handle, name, description, harness, model,
                       system_prompt, allowed_tools, default_cwd, permission_mode,
                       avatar, hue, extra_args, command, retired_at, dm_channel_id,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id) DO UPDATE SET
                       handle=excluded.handle, name=excluded.name,
                       description=excluded.description, harness=excluded.harness,
                       model=excluded.model, system_prompt=excluded.system_prompt,
                       allowed_tools=excluded.allowed_tools, default_cwd=excluded.default_cwd,
                       permission_mode=excluded.permission_mode,
                       avatar=excluded.avatar, extra_args=excluded.extra_args,
                       command=excluded.command,
                       retired_at=COALESCE(agents.retired_at, excluded.retired_at),
                       dm_channel_id=COALESCE(excluded.dm_channel_id, agents.dm_channel_id),
                       updated_at=excluded.updated_at""",
                (
                    agent.agent_id, agent.handle, agent.name, agent.description,
                    agent.harness, agent.model, agent.system_prompt,
                    _dump(agent.allowed_tools), agent.default_cwd, agent.permission_mode,
                    _dump(avatar), hue, _dump(agent.extra_args), _dump(agent.command),
                    agent.retired_at, agent.dm_channel_id,
                    existing["created_at"] if existing else agent.created_at, agent.updated_at,
                ),
            )

    def get_agent(self, agent_id: str) -> Agent:
        row = self.conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return _agent(row)

    def list_agents(self, include_retired: bool = False) -> list[Agent]:
        where = "" if include_retired else " WHERE retired_at IS NULL"
        return [_agent(row) for row in self.conn.execute(f"SELECT * FROM agents{where} ORDER BY agent_id")]

    def retire_agent(self, agent_id: str) -> Agent:
        with self.transaction():
            cursor = self.conn.execute("UPDATE agents SET retired_at = COALESCE(retired_at, ?), updated_at = ? WHERE agent_id = ?",
                                       (utc_now(), utc_now(), agent_id))
            if not cursor.rowcount:
                raise KeyError(agent_id)
            return self.get_agent(agent_id)

    def set_agent_dm_channel(self, agent_id: str, channel_id: str) -> None:
        with self.transaction():
            cursor = self.conn.execute("UPDATE agents SET dm_channel_id = ? WHERE agent_id = ?",
                                       (channel_id, agent_id))
            if not cursor.rowcount:
                raise KeyError(agent_id)

    def create_channel(self, channel: Channel, members: list[tuple[str, str]]) -> None:
        with self.transaction():
            self.conn.execute(
                """INSERT INTO channels (
                       channel_id, kind, name, cwd, cwd_managed, next_seq,
                       rendered_chars_since_checkpoint, created_at, archived_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    channel.channel_id, channel.kind, channel.name, channel.cwd,
                    int(channel.cwd_managed), channel.next_seq,
                    channel.rendered_chars_since_checkpoint, channel.created_at,
                    channel.archived_at,
                ),
            )
            for member_kind, member_id in members:
                self.conn.execute(
                    """INSERT INTO channel_members
                       (channel_id, member_kind, member_id, joined_at)
                       VALUES (?, ?, ?, ?)""",
                    (channel.channel_id, member_kind, member_id, utc_now()),
                )

    def get_channel(self, channel_id: str) -> Channel:
        row = self.conn.execute("SELECT * FROM channels WHERE channel_id = ?", (channel_id,)).fetchone()
        if row is None:
            raise KeyError(channel_id)
        return _channel(row)

    def list_channels(self, human_id: str | None = None) -> list[Channel]:
        if human_id is None:
            rows = self.conn.execute("SELECT * FROM channels ORDER BY created_at, channel_id")
        else:
            rows = self.conn.execute(
                """SELECT c.* FROM channels AS c
                   JOIN channel_members AS m ON m.channel_id = c.channel_id
                   WHERE m.member_kind = 'human' AND m.member_id = ?
                   ORDER BY c.created_at, c.channel_id""",
                (human_id,),
            )
        return [_channel(row) for row in rows]

    def members(self, channel_id: str) -> list[dict[str, str]]:
        if self.conn.execute("SELECT 1 FROM channels WHERE channel_id = ?", (channel_id,)).fetchone() is None:
            raise KeyError(channel_id)
        return [
            dict(row)
            for row in self.conn.execute(
                """SELECT member_kind, member_id, joined_at FROM channel_members
                   WHERE channel_id = ? ORDER BY joined_at, member_kind, member_id""",
                (channel_id,),
            )
        ]

    def add_member(self, channel_id: str, kind: str, id: str) -> bool:
        """Insert a member and report whether it was new."""
        with self.transaction():
            if self.conn.execute("SELECT 1 FROM channels WHERE channel_id = ?", (channel_id,)).fetchone() is None:
                raise KeyError(channel_id)
            cursor = self.conn.execute(
                """INSERT INTO channel_members (channel_id, member_kind, member_id, joined_at)
                   VALUES (?, ?, ?, ?) ON CONFLICT(channel_id, member_kind, member_id) DO NOTHING""",
                (channel_id, kind, id, utc_now()),
            )
            return cursor.rowcount == 1

    def remove_member(self, channel_id: str, kind: str, id: str) -> None:
        with self.transaction():
            cursor = self.conn.execute(
                """DELETE FROM channel_members
                   WHERE channel_id = ? AND member_kind = ? AND member_id = ?""",
                (channel_id, kind, id),
            )
            if cursor.rowcount == 0:
                raise KeyError((channel_id, kind, id))

    def set_channel_cwd(self, channel_id: str, cwd: str, managed: bool) -> None:
        with self.transaction():
            cursor = self.conn.execute(
                "UPDATE channels SET cwd = ?, cwd_managed = ? WHERE channel_id = ?",
                (cwd, int(managed), channel_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(channel_id)

    def archive_channel(self, channel_id: str) -> None:
        with self.transaction():
            cursor = self.conn.execute(
                "UPDATE channels SET archived_at = COALESCE(archived_at, ?) WHERE channel_id = ?",
                (utc_now(), channel_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(channel_id)

    def patch_channel(self, channel_id: str, *, name: str | None = None,
                      archived: bool | None = None) -> Channel:
        with self.transaction():
            channel = self.get_channel(channel_id)
            if name is not None:
                if not name.strip():
                    raise WorkspaceError("channel name cannot be empty")
                self.conn.execute("UPDATE channels SET name = ? WHERE channel_id = ?", (name.strip(), channel_id))
            if archived is not None:
                self.conn.execute("UPDATE channels SET archived_at = ? WHERE channel_id = ?",
                                  (utc_now() if archived and channel.archived_at is None else
                                   channel.archived_at if archived else None, channel_id))
            return self.get_channel(channel_id)

    def append_event(
        self,
        channel_id: str,
        kind: str,
        author_kind: str,
        author_id: str,
        payload: dict[str, Any],
        *,
        run_id: str | None = None,
        chain_id: int | None = None,
        hop: int = 0,
        rendered_chars: int = 0,
    ) -> Event:
        with self.transaction():
            channel = self.conn.execute(
                "SELECT next_seq FROM channels WHERE channel_id = ?", (channel_id,),
            ).fetchone()
            if channel is None:
                raise KeyError(channel_id)
            seq = channel["next_seq"]

            # A human event without a parent starts a new chain. Predicting the
            # next AUTOINCREMENT id is safe under BEGIN IMMEDIATE and lets the
            # row point to itself without ever updating an immutable event.
            event_id = self.conn.execute(
                """SELECT max(
                       COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'events'), 0),
                       COALESCE((SELECT max(id) FROM events), 0)
                   ) + 1"""
            ).fetchone()[0]
            if author_kind == "human" and chain_id is None:
                chain_id = event_id
            elif chain_id is None:
                raise WorkspaceError("non-human events must include their originating chain_id")

            self.conn.execute(
                """INSERT INTO events (
                       id, channel_id, seq, ts, kind, author_kind, author_id,
                       run_id, chain_id, hop, payload
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, channel_id, seq, utc_now(), kind, author_kind, author_id,
                    run_id, chain_id, hop, _dump(payload),
                ),
            )
            self.conn.execute(
                """UPDATE channels
                   SET next_seq = ?,
                       rendered_chars_since_checkpoint = rendered_chars_since_checkpoint + ?
                   WHERE channel_id = ?""",
                (seq + 1, rendered_chars, channel_id),
            )
            self._index_event(channel_id, seq, kind, payload)
            row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            return _event(row)

    def _index_event(self, channel_id: str, seq: int, kind: str, payload: dict[str, Any]) -> None:
        if kind == "message":
            self.conn.execute("INSERT INTO search_fts(kind, channel_id, seq, text) VALUES (?, ?, ?, ?)",
                              (kind, channel_id, seq, payload.get("text", "")))
        elif kind == "tool_call":
            summary = payload.get("summary") or payload.get("label") or ""
            self.conn.execute("INSERT INTO search_fts(kind, channel_id, seq, text) VALUES (?, ?, ?, ?)",
                              (kind, channel_id, seq, summary))
        elif kind == "message_edit":
            target = payload.get("target_seq")
            self.conn.execute("DELETE FROM search_fts WHERE kind = 'message' AND channel_id = ? AND seq = ?",
                              (channel_id, target))
            if not payload.get("deleted"):
                original = self.conn.execute(
                    "SELECT payload FROM events WHERE channel_id = ? AND seq = ? AND kind = 'message'",
                    (channel_id, target),
                ).fetchone()
                if original:
                    latest_text = self.conn.execute(
                        """SELECT json_extract(payload, '$.text') AS text FROM events
                           WHERE channel_id = ? AND kind = 'message_edit'
                           AND seq <= ? AND json_extract(payload, '$.target_seq') = ?
                           AND json_type(payload, '$.text') IS NOT NULL
                           ORDER BY seq DESC LIMIT 1""",
                        (channel_id, seq, target),
                    ).fetchone()
                    text = (latest_text["text"] if latest_text else
                            _load(original["payload"]).get("text", ""))
                    self.conn.execute("INSERT INTO search_fts(kind, channel_id, seq, text) VALUES ('message', ?, ?, ?)",
                                      (channel_id, target, text))

    def _rebuild_search(self) -> None:
        self.conn.execute("DELETE FROM search_fts")
        for row in self.conn.execute("SELECT channel_id, seq, kind, payload FROM events ORDER BY id"):
            self._index_event(row["channel_id"], row["seq"], row["kind"], _load(row["payload"]))

    def events(
        self,
        channel_id: str,
        from_seq: int = 1,
        to_seq: int | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        sql = "SELECT * FROM events WHERE channel_id = ? AND seq >= ?"
        params: list[Any] = [channel_id, from_seq]
        if to_seq is not None:
            sql += " AND seq <= ?"
            params.append(to_seq)
        sql += " ORDER BY seq ASC"
        if limit is not None:
            if limit <= 0:
                return []
            sql += " LIMIT ?"
            params.append(limit)
        return [_event(row) for row in self.conn.execute(sql, params)]

    def scrollback(
        self,
        channel_id: str,
        *,
        before_seq: int | None = None,
        after_seq: int | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Read one ascending scrollback page using exclusive sequence cursors.

        An unbounded query returns the latest page. A before-only query first
        selects the nearest preceding rows, then restores ascending order.
        """
        if limit <= 0:
            return []

        if after_seq is not None:
            clauses = ["channel_id = ?", "seq > ?"]
            params: list[Any] = [channel_id, after_seq]
            if before_seq is not None:
                clauses.append("seq < ?")
                params.append(before_seq)
            rows = self.conn.execute(
                f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY seq ASC LIMIT ?",
                [*params, limit],
            )
            return [_event(row) for row in rows]

        if before_seq is not None:
            rows = list(self.conn.execute(
                """SELECT * FROM events WHERE channel_id = ? AND seq < ?
                   ORDER BY seq DESC LIMIT ?""",
                (channel_id, before_seq, limit),
            ))
            rows.reverse()
            return [_event(row) for row in rows]

        rows = list(self.conn.execute(
            "SELECT * FROM events WHERE channel_id = ? ORDER BY seq DESC LIMIT ?",
            (channel_id, limit),
        ))
        rows.reverse()
        return [_event(row) for row in rows]

    def get_event(self, channel_id: str, seq: int) -> Event:
        row = self.conn.execute(
            "SELECT * FROM events WHERE channel_id = ? AND seq = ?", (channel_id, seq),
        ).fetchone()
        if row is None:
            raise KeyError((channel_id, seq))
        return _event(row)

    def replay(self, last_id: int, channel_ids: list[str], limit: int) -> list[Event]:
        if not channel_ids or limit <= 0:
            return []
        placeholders = ",".join("?" for _ in channel_ids)
        rows = self.conn.execute(
            f"SELECT * FROM events WHERE id > ? AND channel_id IN ({placeholders}) ORDER BY id ASC LIMIT ?",
            [last_id, *channel_ids, limit],
        )
        return [_event(row) for row in rows]

    def enqueue(
        self,
        channel_id: str,
        event_seq: int,
        agent_id: str | None = None,
        wait_for: list[str] | None = None,
        state: str = "awaiting_agent",
    ) -> QueueItem:
        with self.transaction():
            cursor = self.conn.execute(
                """INSERT INTO dispatch_queue
                   (channel_id, event_seq, agent_id, wait_for, state, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (channel_id, event_seq, agent_id, _dump(wait_for or []), state, utc_now()),
            )
            row = self.conn.execute(
                "SELECT * FROM dispatch_queue WHERE queue_id = ?", (cursor.lastrowid,),
            ).fetchone()
            return _queue_item(row)

    def queue(
        self, channel_id: str | None = None, state: str | None = None,
        event_seq: int | None = None,
    ) -> list[QueueItem]:
        clauses: list[str] = []
        params: list[Any] = []
        if channel_id is not None:
            clauses.append("channel_id = ?")
            params.append(channel_id)
        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        if event_seq is not None:
            clauses.append("event_seq = ?")
            params.append(event_seq)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM dispatch_queue{where} ORDER BY created_at, queue_id", params,
        )
        return [_queue_item(row) for row in rows]

    def get_queue_item(self, queue_id: int) -> QueueItem:
        row = self.conn.execute(
            "SELECT * FROM dispatch_queue WHERE queue_id = ?", (queue_id,),
        ).fetchone()
        if row is None:
            raise KeyError(queue_id)
        return _queue_item(row)

    def update_queue(
        self,
        queue_id: int,
        *,
        state: str | None = None,
        agent_id: str | None | object = _UNSET,
        wait_for: list[str] | None = None,
    ) -> None:
        updates: dict[str, Any] = {}
        if state is not None:
            updates["state"] = state
        if agent_id is not _UNSET:
            updates["agent_id"] = agent_id
        if wait_for is not None:
            updates["wait_for"] = _dump(wait_for)
        with self.transaction():
            if not updates:
                if self.conn.execute("SELECT 1 FROM dispatch_queue WHERE queue_id = ?", (queue_id,)).fetchone() is None:
                    raise KeyError(queue_id)
                return
            assignments = ", ".join(f"{column} = ?" for column in updates)
            values = [updates[column] for column in updates]
            cursor = self.conn.execute(
                f"UPDATE dispatch_queue SET {assignments} WHERE queue_id = ?",
                [*values, queue_id],
            )
            if cursor.rowcount == 0:
                raise KeyError(queue_id)

    def create_run(self, run: Run) -> bool:
        with self.transaction():
            cursor = self.conn.execute(
                """INSERT INTO runs (
                       run_id, channel_id, agent_id, trigger_seq, delta_start_seq,
                       delta_end_seq, session_mode, harness, harness_session_id,
                       cwd, pgid, status, error, exit_code, started_at, ended_at,
                       tokens_in, tokens_out, duration_ms, tokens_cached_in,
                       tokens_cache_creation, tokens_reasoning, tokens_total,
                       model_context_window, context_tokens
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(channel_id, trigger_seq, agent_id) DO NOTHING""",
                (
                    run.run_id, run.channel_id, run.agent_id, run.trigger_seq,
                    run.delta_start_seq, run.delta_end_seq, run.session_mode,
                    run.harness, run.harness_session_id, run.cwd, run.pgid,
                    run.status, _dump(run.error) if isinstance(run.error, dict) else run.error,
                    run.exit_code, run.started_at,
                    run.ended_at, run.tokens_in, run.tokens_out, run.duration_ms,
                    run.tokens_cached_in, run.tokens_cache_creation,
                    run.tokens_reasoning, run.tokens_total, run.model_context_window,
                    run.context_tokens,
                ),
            )
            return cursor.rowcount == 1

    def get_run(self, run_id: str) -> Run:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _run(row)

    def list_runs(self, channel_id: str | None = None, active_only: bool = False, *,
                  agent_id: str | None = None, status: str | None = None,
                  limit: int | None = None, newest_first: bool = False) -> list[Run]:
        clauses: list[str] = []
        params: list[Any] = []
        if channel_id is not None:
            clauses.append("channel_id = ?")
            params.append(channel_id)
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if status not in (None, "active", "terminal"):
            raise WorkspaceError("run status filter must be active or terminal")
        if active_only or status == "active":
            clauses.append("status NOT IN ('completed', 'failed', 'cancelled')")
        elif status == "terminal":
            clauses.append("status IN ('completed', 'failed', 'cancelled')")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        if limit is not None and limit <= 0:
            return []
        suffix = " LIMIT ?" if limit is not None else ""
        if limit is not None:
            params.append(limit)
        direction = "DESC" if newest_first else "ASC"
        rows = self.conn.execute(
            f"SELECT * FROM runs{where} ORDER BY started_at {direction}, run_id {direction}{suffix}", params,
        )
        return [_run(row) for row in rows]

    def update_run(self, run_id: str, **allowed_fields: Any) -> None:
        unknown = set(allowed_fields) - _RUN_UPDATE_FIELDS
        if unknown:
            raise ValueError(f"run fields cannot be updated: {', '.join(sorted(unknown))}")
        with self.transaction():
            if "error" in allowed_fields and isinstance(allowed_fields["error"], dict):
                allowed_fields["error"] = _dump(allowed_fields["error"])
            if not allowed_fields:
                if self.conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone() is None:
                    raise KeyError(run_id)
                return
            assignments = ", ".join(f"{field} = ?" for field in allowed_fields)
            cursor = self.conn.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ?",
                [*allowed_fields.values(), run_id],
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)

    def get_session(self, agent_id: str, channel_id: str) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM agent_sessions WHERE agent_id = ? AND channel_id = ?",
            (agent_id, channel_id),
        ).fetchone()
        return None if row is None else _session(row)

    def put_session(self, session: Session) -> None:
        with self.transaction():
            self.conn.execute(
                """INSERT INTO agent_sessions (
                       agent_id, channel_id, harness, harness_session_id, cwd,
                       last_seen_seq, config_fingerprint, last_run_status, last_used_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, channel_id) DO UPDATE SET
                       harness=excluded.harness,
                       harness_session_id=excluded.harness_session_id,
                       cwd=excluded.cwd, last_seen_seq=excluded.last_seen_seq,
                       config_fingerprint=excluded.config_fingerprint,
                       last_run_status=excluded.last_run_status,
                       last_used_at=excluded.last_used_at""",
                (
                    session.agent_id, session.channel_id, session.harness,
                    session.harness_session_id, session.cwd, session.last_seen_seq,
                    session.config_fingerprint, session.last_run_status,
                    session.last_used_at,
                ),
            )

    def set_checkpoint_counter(self, channel_id: str, value: int) -> None:
        with self.transaction():
            cursor = self.conn.execute(
                "UPDATE channels SET rendered_chars_since_checkpoint = ? WHERE channel_id = ?",
                (value, channel_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(channel_id)

    def put_attachment(self, attachment: Attachment) -> None:
        with self.transaction():
            self.conn.execute(
                """INSERT INTO attachments (
                       attachment_id, channel_id, filename, media_type, size_bytes,
                       sha256, path, message_seq, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attachment.attachment_id, attachment.channel_id, attachment.filename,
                    attachment.media_type, attachment.size_bytes, attachment.sha256,
                    attachment.path, attachment.message_seq, attachment.created_at,
                ),
            )

    def get_attachment(self, attachment_id: str) -> Attachment:
        row = self.conn.execute(
            "SELECT * FROM attachments WHERE attachment_id = ?", (attachment_id,),
        ).fetchone()
        if row is None:
            raise KeyError(attachment_id)
        return _attachment(row)

    def bind_attachment(self, attachment_id: str, message_seq: int) -> None:
        with self.transaction():
            cursor = self.conn.execute(
                """UPDATE attachments SET message_seq = ?
                   WHERE attachment_id = ? AND message_seq IS NULL""",
                (message_seq, attachment_id),
            )
            if cursor.rowcount == 0:
                raise WorkspaceError("attachment is missing or already sent")

    def message_attachments(self, channel_id: str, seqs: list[int]) -> list[Attachment]:
        if not seqs:
            return []
        placeholders = ",".join("?" for _ in seqs)
        rows = self.conn.execute(
            f"""SELECT * FROM attachments
                WHERE channel_id = ? AND message_seq IN ({placeholders})
                ORDER BY message_seq, created_at, attachment_id""",
            [channel_id, *seqs],
        )
        return [_attachment(row) for row in rows]

    def delete_attachment(self, attachment_id: str) -> None:
        with self.transaction():
            cursor = self.conn.execute(
                "DELETE FROM attachments WHERE attachment_id = ? AND message_seq IS NULL",
                (attachment_id,),
            )
            if cursor.rowcount == 0:
                self.get_attachment(attachment_id)
                raise WorkspaceError("a sent attachment cannot be deleted")

    def attachment_channel_bytes(self, channel_id: str) -> int:
        return self.conn.execute("SELECT COALESCE(sum(size_bytes), 0) FROM attachments WHERE channel_id = ?",
                                 (channel_id,)).fetchone()[0]

    def expired_unsent_attachments(self, cutoff: str) -> list[Attachment]:
        return [_attachment(row) for row in self.conn.execute(
            "SELECT * FROM attachments WHERE message_seq IS NULL AND created_at < ? ORDER BY created_at",
            (cutoff,),
        )]

    def set_read_cursor(self, channel_id: str, human_id: str, seq: int) -> int:
        with self.transaction():
            channel = self.get_channel(channel_id)
            if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0 or seq >= channel.next_seq:
                raise WorkspaceError("read sequence is outside the channel")
            if not self.conn.execute(
                "SELECT 1 FROM channel_members WHERE channel_id = ? AND member_kind = 'human' AND member_id = ?",
                (channel_id, human_id),
            ).fetchone():
                raise WorkspaceError("human is not a channel member")
            self.conn.execute(
                """INSERT INTO read_cursors(channel_id, human_id, seq) VALUES (?, ?, ?)
                   ON CONFLICT(channel_id, human_id) DO UPDATE SET seq = max(read_cursors.seq, excluded.seq)""",
                (channel_id, human_id, seq),
            )
            return self.conn.execute("SELECT seq FROM read_cursors WHERE channel_id = ? AND human_id = ?",
                                     (channel_id, human_id)).fetchone()[0]

    def channel_summary(self, channel_id: str, human_id: str) -> dict[str, Any]:
        channel = self.get_channel(channel_id)
        members = self.members(channel_id)
        cursor = self.conn.execute("SELECT seq FROM read_cursors WHERE channel_id = ? AND human_id = ?",
                                   (channel_id, human_id)).fetchone()
        read_seq = cursor[0] if cursor else 0
        unread = self.conn.execute(
            """SELECT count(*) FROM events AS e WHERE e.channel_id = ? AND e.seq > ?
               AND e.kind = 'message' AND NOT (e.author_kind = 'human' AND e.author_id = ?)
               AND EXISTS (SELECT 1 FROM search_fts AS f WHERE f.channel_id = e.channel_id
                           AND f.seq = e.seq AND f.kind = 'message')""",
            (channel_id, read_seq, human_id),
        ).fetchone()[0]
        last = self.conn.execute("SELECT ts FROM events WHERE channel_id = ? ORDER BY seq DESC LIMIT 1",
                                 (channel_id,)).fetchone()
        preview = None
        for row in self.conn.execute(
            "SELECT seq, kind, author_id, payload FROM events WHERE channel_id = ? AND kind IN ('message', 'tool_call') ORDER BY seq DESC",
            (channel_id,),
        ):
            indexed = self.conn.execute("SELECT text FROM search_fts WHERE channel_id = ? AND seq = ? AND kind = ?",
                                        (channel_id, row["seq"], row["kind"])).fetchone()
            if indexed is None:
                continue
            preview = {"seq": row["seq"], "kind": row["kind"], "author_id": row["author_id"],
                       "text_excerpt": indexed["text"][:160]}
            break
        active_runs = [
            {"run_id": r["run_id"], "agent_id": r["agent_id"], "status": r["status"],
             "started_at": r["started_at"]}
            for r in self.conn.execute(
                """SELECT run_id, agent_id, status, started_at FROM runs WHERE channel_id = ?
                   AND status NOT IN ('completed', 'failed', 'cancelled') ORDER BY started_at, run_id""",
                (channel_id,),
            )
        ]
        return {**asdict(channel), "members": members, "last_activity_at": last["ts"] if last else channel.created_at,
                "preview": preview, "unread_count": unread, "active_runs": active_runs}

    def list_channel_summaries(self, human_id: str) -> list[dict[str, Any]]:
        return [self.channel_summary(channel.channel_id, human_id)
                for channel in self.list_channels(human_id)]

    def put_harness_limits(self, harness: str, snapshot: dict[str, Any]) -> None:
        with self.transaction():
            self.conn.execute(
                """INSERT INTO harness_limits(harness, snapshot, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(harness) DO UPDATE SET snapshot = excluded.snapshot, updated_at = excluded.updated_at""",
                (harness, _dump(snapshot), utc_now()),
            )

    def get_harness_limits(self, harness: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT snapshot FROM harness_limits WHERE harness = ?", (harness,)).fetchone()
        return _load(row["snapshot"]) if row else None

    def usage(self, group_by: str = "agent", since: str | None = None) -> list[dict[str, Any]]:
        if group_by not in {"agent", "channel", "day"}:
            raise WorkspaceError("usage group_by must be agent, channel, or day")
        if since is not None:
            try:
                if len(since) == 10:
                    parsed = datetime.combine(date.fromisoformat(since), datetime.min.time(), timezone.utc)
                else:
                    parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    parsed = parsed.astimezone(timezone.utc)
                since = parsed.isoformat()
            except (ValueError, TypeError, AttributeError) as exc:
                raise WorkspaceError("since must be an ISO date or timestamp") from exc
        expr = {"agent": "agent_id", "channel": "channel_id", "day": "date(started_at)"}[group_by]
        predicates = []
        if group_by == "day":
            predicates.append("started_at IS NOT NULL")
        if since is not None:
            predicates.append("julianday(started_at) >= julianday(?)")
        where = "WHERE " + " AND ".join(predicates) if predicates else ""
        rows = self.conn.execute(
            f"""SELECT {expr} AS key, count(*) AS run_count, sum(tokens_in) AS tokens_in,
                sum(tokens_out) AS tokens_out, sum(tokens_cached_in) AS tokens_cached_in,
                sum(tokens_cache_creation) AS tokens_cache_creation,
                sum(tokens_reasoning) AS tokens_reasoning, sum(tokens_total) AS tokens_total
                FROM runs {where} GROUP BY {expr} ORDER BY key""",
            (since,) if since is not None else (),
        )
        return [{group_by: row["key"], **{key: row[key] for key in row.keys() if key != "key"}} for row in rows]

    def get_human_profile(self, human_id: str = "local") -> dict[str, str]:
        row = self.conn.execute("SELECT display_name FROM human_profiles WHERE human_id = ?", (human_id,)).fetchone()
        return {"human_id": human_id, "display_name": row["display_name"] if row else "You"}

    def set_human_profile(self, human_id: str, display_name: str) -> dict[str, str]:
        if not display_name.strip():
            raise WorkspaceError("display name cannot be empty")
        with self.transaction():
            self.conn.execute(
                """INSERT INTO human_profiles(human_id, display_name) VALUES (?, ?)
                   ON CONFLICT(human_id) DO UPDATE SET display_name = excluded.display_name""",
                (human_id, display_name.strip()),
            )
        return self.get_human_profile(human_id)

    def search(self, q: str, *, channel_id: str | None = None,
               kinds: list[str] | None = None, limit: int = 50) -> dict[str, list[dict[str, Any]]]:
        if limit <= 0 or not q.strip():
            return {"channels": [], "agents": [], "messages": []}
        phrase = '"' + q.strip().replace('"', '""') + '"'
        params: list[Any] = [phrase]
        clauses = ["search_fts MATCH ?"]
        if channel_id is not None:
            clauses.append("f.channel_id = ?")
            params.append(channel_id)
        if kinds is not None:
            if not kinds:
                return {"channels": [], "agents": [], "messages": []}
            clauses.append("f.kind IN (" + ",".join("?" for _ in kinds) + ")")
            params.extend(kinds)
        rows = self.conn.execute(
            f"""SELECT f.channel_id, CAST(f.seq AS INTEGER) AS seq, f.kind, f.text,
                e.author_id FROM search_fts AS f JOIN events AS e
                ON e.channel_id = f.channel_id AND e.seq = f.seq
                WHERE {' AND '.join(clauses)} ORDER BY e.id DESC LIMIT ?""",
            (*params, limit),
        )
        messages = [dict(row) for row in rows]
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        channels = [dict(row) for row in self.conn.execute(
            "SELECT channel_id, name FROM channels WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT ?",
            (term, limit),
        )]
        agents = [dict(row) for row in self.conn.execute(
            "SELECT agent_id, handle, name FROM agents WHERE retired_at IS NULL AND (handle LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\') ORDER BY handle LIMIT ?",
            (term, term, limit),
        )]
        return {"channels": channels, "agents": agents, "messages": messages}
