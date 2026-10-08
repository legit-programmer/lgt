PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    harness TEXT NOT NULL,
    model TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    allowed_tools TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(allowed_tools)),
    default_cwd TEXT,
    permission_mode TEXT NOT NULL DEFAULT 'bypass',
    avatar TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(avatar)),
    hue INTEGER,
    extra_args TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(extra_args)),
    command TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(command)),
    retired_at TEXT,
    dm_channel_id TEXT REFERENCES channels(channel_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('channel', 'dm')),
    name TEXT NOT NULL,
    cwd TEXT NOT NULL,
    cwd_managed INTEGER NOT NULL CHECK (cwd_managed IN (0, 1)),
    next_seq INTEGER NOT NULL DEFAULT 1 CHECK (next_seq >= 1),
    rendered_chars_since_checkpoint INTEGER NOT NULL DEFAULT 0 CHECK (rendered_chars_since_checkpoint >= 0),
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS channel_members (
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    member_kind TEXT NOT NULL CHECK (member_kind IN ('human', 'agent')),
    member_id TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (channel_id, member_kind, member_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    trigger_seq INTEGER NOT NULL,
    delta_start_seq INTEGER NOT NULL,
    delta_end_seq INTEGER NOT NULL,
    session_mode TEXT NOT NULL CHECK (session_mode IN ('resume', 'cold')),
    harness TEXT NOT NULL,
    harness_session_id TEXT,
    cwd TEXT NOT NULL,
    pgid INTEGER,
    status TEXT NOT NULL,
    error TEXT,
    exit_code INTEGER,
    started_at TEXT,
    ended_at TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    tokens_cached_in INTEGER NOT NULL DEFAULT 0,
    tokens_cache_creation INTEGER NOT NULL DEFAULT 0,
    tokens_reasoning INTEGER NOT NULL DEFAULT 0,
    tokens_total INTEGER NOT NULL DEFAULT 0,
    model_context_window INTEGER,
    context_tokens INTEGER,
    cost_usd REAL NOT NULL DEFAULT 0,
    UNIQUE (channel_id, trigger_seq, agent_id)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    harness TEXT NOT NULL,
    harness_session_id TEXT,
    cwd TEXT NOT NULL,
    last_seen_seq INTEGER NOT NULL,
    config_fingerprint TEXT NOT NULL,
    last_run_status TEXT NOT NULL CHECK (last_run_status IN ('clean', 'dirty')),
    last_used_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, channel_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    author_kind TEXT NOT NULL,
    author_id TEXT NOT NULL,
    run_id TEXT REFERENCES runs(run_id) ON DELETE RESTRICT,
    chain_id INTEGER NOT NULL REFERENCES events(id) DEFERRABLE INITIALLY DEFERRED,
    hop INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    UNIQUE (channel_id, seq)
);

CREATE TABLE IF NOT EXISTS dispatch_queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    event_seq INTEGER NOT NULL,
    agent_id TEXT REFERENCES agents(agent_id) ON DELETE RESTRICT,
    wait_for TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(wait_for)),
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (channel_id, event_seq) REFERENCES events(channel_id, seq) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS attachments (
    attachment_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    message_seq INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (channel_id, message_seq) REFERENCES events(channel_id, seq) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS read_cursors (
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    human_id TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0 CHECK (seq >= 0),
    PRIMARY KEY (channel_id, human_id)
);

CREATE TABLE IF NOT EXISTS harness_limits (
    harness TEXT PRIMARY KEY,
    snapshot TEXT NOT NULL CHECK (json_valid(snapshot)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_profiles (
    human_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS attachments_message_idx ON attachments(channel_id, message_seq);
CREATE INDEX IF NOT EXISTS dispatch_queue_event_idx ON dispatch_queue(channel_id, event_seq);

CREATE INDEX IF NOT EXISTS events_global_cursor_idx ON events(id);
CREATE INDEX IF NOT EXISTS events_channel_seq_idx ON events(channel_id, seq);
CREATE INDEX IF NOT EXISTS runs_channel_status_idx ON runs(channel_id, status);
CREATE INDEX IF NOT EXISTS dispatch_queue_order_idx ON dispatch_queue(created_at, queue_id);
CREATE INDEX IF NOT EXISTS dispatch_queue_channel_state_idx ON dispatch_queue(channel_id, state, created_at, queue_id);

-- Replace the initial one-status-per-run guard: lifecycle notifications may
-- include starting/running, while each run may have only one terminal event.
DROP INDEX IF EXISTS events_one_run_status_idx;
CREATE UNIQUE INDEX events_one_run_status_idx
    ON events(run_id)
    WHERE kind = 'run_status'
      AND run_id IS NOT NULL
      AND json_extract(payload, '$.status') IN ('completed', 'failed', 'cancelled');

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;

-- A channel's cwd may change between runs. The orchestrator records each
-- change as a cwd_changed event; sessions keyed to the old cwd go cold.
DROP TRIGGER IF EXISTS channels_cwd_immutable;

CREATE TRIGGER IF NOT EXISTS channel_members_agent_exists
BEFORE INSERT ON channel_members
WHEN NEW.member_kind = 'agent' AND NOT EXISTS (
    SELECT 1 FROM agents WHERE agent_id = NEW.member_id
)
BEGIN
    SELECT RAISE(ABORT, 'channel member agent does not exist');
END;

CREATE TRIGGER IF NOT EXISTS channel_members_agent_update_exists
BEFORE UPDATE OF member_kind, member_id ON channel_members
WHEN NEW.member_kind = 'agent' AND NOT EXISTS (
    SELECT 1 FROM agents WHERE agent_id = NEW.member_id
)
BEGIN
    SELECT RAISE(ABORT, 'channel member agent does not exist');
END;

CREATE TRIGGER IF NOT EXISTS attachments_bind_once
BEFORE UPDATE ON attachments
WHEN OLD.message_seq IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'a sent attachment is immutable');
END;

CREATE TRIGGER IF NOT EXISTS attachments_keep_sent
BEFORE DELETE ON attachments
WHEN OLD.message_seq IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'a sent attachment is immutable');
END;
