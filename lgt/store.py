"""SQLite persistence for the multi-agent workspace."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import (
    Agent, Attachment, Channel, Event, QueueItem, Run, Session, WorkspaceError, utc_now,
)


_UNSET = object()
_RUN_UPDATE_FIELDS = frozenset({
    "trigger_seq", "delta_start_seq", "delta_end_seq", "session_mode", "harness",
    "harness_session_id", "cwd", "pgid", "status", "error", "exit_code",
    "started_at", "ended_at", "tokens_in", "tokens_out", "cost_usd",
})


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str) -> Any:
    return json.loads(value)


def _agent(row: sqlite3.Row) -> Agent:
    return Agent(
        agent_id=row["agent_id"], handle=row["handle"], name=row["name"],
        description=row["description"], harness=row["harness"], model=row["model"],
        system_prompt=row["system_prompt"], allowed_tools=_load(row["allowed_tools"]),
        default_cwd=row["default_cwd"], permission_mode=row["permission_mode"],
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
    return Run(
        run_id=row["run_id"], channel_id=row["channel_id"], agent_id=row["agent_id"],
        trigger_seq=row["trigger_seq"], delta_start_seq=row["delta_start_seq"],
        delta_end_seq=row["delta_end_seq"], session_mode=row["session_mode"],
        harness=row["harness"], cwd=row["cwd"],
        harness_session_id=row["harness_session_id"], pgid=row["pgid"],
        status=row["status"], error=row["error"], exit_code=row["exit_code"],
        started_at=row["started_at"], ended_at=row["ended_at"],
        tokens_in=row["tokens_in"], tokens_out=row["tokens_out"], cost_usd=row["cost_usd"],
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
            self.conn.execute(
                """INSERT INTO agents (
                       agent_id, handle, name, description, harness, model,
                       system_prompt, allowed_tools, default_cwd, permission_mode,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id) DO UPDATE SET
                       handle=excluded.handle, name=excluded.name,
                       description=excluded.description, harness=excluded.harness,
                       model=excluded.model, system_prompt=excluded.system_prompt,
                       allowed_tools=excluded.allowed_tools, default_cwd=excluded.default_cwd,
                       permission_mode=excluded.permission_mode,
                       created_at=excluded.created_at, updated_at=excluded.updated_at""",
                (
                    agent.agent_id, agent.handle, agent.name, agent.description,
                    agent.harness, agent.model, agent.system_prompt,
                    _dump(agent.allowed_tools), agent.default_cwd, agent.permission_mode,
                    agent.created_at, agent.updated_at,
                ),
            )

    def get_agent(self, agent_id: str) -> Agent:
        row = self.conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return _agent(row)

    def list_agents(self) -> list[Agent]:
        return [_agent(row) for row in self.conn.execute("SELECT * FROM agents ORDER BY agent_id")]

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
            row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            return _event(row)

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
                       tokens_in, tokens_out, cost_usd
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(channel_id, trigger_seq, agent_id) DO NOTHING""",
                (
                    run.run_id, run.channel_id, run.agent_id, run.trigger_seq,
                    run.delta_start_seq, run.delta_end_seq, run.session_mode,
                    run.harness, run.harness_session_id, run.cwd, run.pgid,
                    run.status, run.error, run.exit_code, run.started_at,
                    run.ended_at, run.tokens_in, run.tokens_out, run.cost_usd,
                ),
            )
            return cursor.rowcount == 1

    def get_run(self, run_id: str) -> Run:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _run(row)

    def list_runs(self, channel_id: str | None = None, active_only: bool = False) -> list[Run]:
        clauses: list[str] = []
        params: list[Any] = []
        if channel_id is not None:
            clauses.append("channel_id = ?")
            params.append(channel_id)
        if active_only:
            clauses.append("status NOT IN ('completed', 'failed', 'cancelled')")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM runs{where} ORDER BY started_at, run_id", params,
        )
        return [_run(row) for row in rows]

    def update_run(self, run_id: str, **allowed_fields: Any) -> None:
        unknown = set(allowed_fields) - _RUN_UPDATE_FIELDS
        if unknown:
            raise ValueError(f"run fields cannot be updated: {', '.join(sorted(unknown))}")
        with self.transaction():
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
