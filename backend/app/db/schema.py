"""Deterministic schema initialisation (idempotent CREATE IF NOT EXISTS) plus the demo seed."""
from __future__ import annotations

SCHEMA: list[str] = [
    """CREATE TABLE IF NOT EXISTS experiments (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active'
    )""",
    """CREATE TABLE IF NOT EXISTS recording_sessions (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES experiments(id),
        started_at TEXT NOT NULL,
        stopped_at TEXT,
        status TEXT NOT NULL,              -- active | stopped | expired
        stop_reason TEXT,
        last_heartbeat_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS observation_events (
        id TEXT PRIMARY KEY,
        session_id TEXT REFERENCES recording_sessions(id),
        experiment_id TEXT NOT NULL REFERENCES experiments(id),
        sequence_number INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        source_modality TEXT NOT NULL,     -- speech | image | text | system
        event_type TEXT NOT NULL,          -- transcript_segment | observation_proposal | visual_observation | correction
        payload_json TEXT NOT NULL,
        model_name TEXT,
        status TEXT NOT NULL,              -- persisted
        idempotency_key TEXT NOT NULL UNIQUE,
        source_event_id TEXT,
        UNIQUE (experiment_id, sequence_number)
    )""",
    """CREATE TABLE IF NOT EXISTS observation_reviews (
        id TEXT PRIMARY KEY,
        observation_id TEXT NOT NULL REFERENCES observation_events(id),
        action TEXT NOT NULL,              -- accept | dispute | correct | reject
        correction_json TEXT,
        reviewer TEXT,
        timestamp TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS media_assets (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES experiments(id),
        file_path TEXT,                    -- NULL: raw bytes were NOT stored (Phase 1 default)
        sha256_hash TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        source_event_id TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS protocol_documents (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES experiments(id),
        version INTEGER NOT NULL,
        content_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS scientific_entities (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES experiments(id),
        entity_type TEXT NOT NULL,
        label TEXT NOT NULL,
        metadata_json TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS scientific_relationships (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES experiments(id),
        source_entity_id TEXT NOT NULL REFERENCES scientific_entities(id),
        target_entity_id TEXT NOT NULL REFERENCES scientific_entities(id),
        relationship_type TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_events_exp_seq ON observation_events(experiment_id, sequence_number)",
    """CREATE TABLE IF NOT EXISTS telemetry_spans (
        id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        parent_id TEXT,
        client_session TEXT,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,                -- span | generation | tool | chain | evaluator | guardrail
        model TEXT,
        prompt_ref TEXT,                   -- e.g. perception.window@v2+steer:ab12cd34ef
        status TEXT NOT NULL,              -- ok | error
        error_code TEXT,
        start_time TEXT NOT NULL,
        latency_ms REAL NOT NULL,
        input_tokens INTEGER,
        output_tokens INTEGER,
        metadata_json TEXT                 -- scalar, content-free metadata only
    )""",
    "CREATE INDEX IF NOT EXISTS ix_spans_time ON telemetry_spans(start_time)",
    """CREATE TABLE IF NOT EXISTS ui_actions (
        id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL REFERENCES experiments(id),
        client_session TEXT,
        recording_session_id TEXT,
        action TEXT NOT NULL,
        source TEXT NOT NULL,              -- user | model
        detail_json TEXT,
        client_timestamp TEXT,
        timestamp TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_ui_actions_exp ON ui_actions(experiment_id, timestamp)",
    # ---- V2: scientific context (Person 2/4 seed format), live session state, retained session frames ----
    """CREATE TABLE IF NOT EXISTS experiment_contexts (
        experiment_id TEXT NOT NULL REFERENCES experiments(id),
        version INTEGER NOT NULL,
        context_json TEXT NOT NULL,        -- full experiment_seed.json shape: steps, samples, constraints, dependencies
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (experiment_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS session_state (
        session_id TEXT PRIMARY KEY REFERENCES recording_sessions(id),
        active_step_id TEXT,
        active_channel_id TEXT,
        tracking_json TEXT NOT NULL DEFAULT '[]',   -- [{label, channel_id, added_at, added_by}]
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS session_frames (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES recording_sessions(id),
        experiment_id TEXT NOT NULL,
        captured_at TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        data BLOB NOT NULL                 -- retained ONLY until the recording session ends, then purged
    )""",
    "CREATE INDEX IF NOT EXISTS ix_frames_session ON session_frames(session_id, captured_at)",
    "CREATE INDEX IF NOT EXISTS ix_reviews_obs ON observation_reviews(observation_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS ix_sessions_exp ON recording_sessions(experiment_id, status)",
    # Seed: one minimal demo experiment.
    """INSERT OR IGNORE INTO experiments (id, name, created_at, status)
       VALUES ('exp-demo', 'Demo: buffer colour-change assay', '2026-01-01T00:00:00+00:00', 'active')""",
]
