from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..config import get_settings
from .database import Database, SqliteDatabase, TursoDatabase
from .schema import SCHEMA


def make_database() -> Database:
    s = get_settings()
    db: Database = TursoDatabase(s.turso_url, s.turso_token) if s.turso_url else SqliteDatabase(s.sqlite_path)
    db.executescript(SCHEMA)
    _seed_demo_protocol(db)
    from ..science.service import seed_database
    seed_database(db)
    return db


def _seed_demo_protocol(db: Database) -> None:
    """Load the demo protocol for exp-demo once (idempotent; never overwrites newer versions)."""
    path = Path(__file__).resolve().parents[2] / "steering" / "protocols" / "demo-colour-assay.json"
    if not path.exists():
        return
    db.execute(
        "INSERT INTO protocol_documents (id, experiment_id, version, content_json, created_at) "
        "SELECT 'prot-demo-v1', 'exp-demo', 1, ?, '2026-01-01T00:00:00+00:00' "
        "WHERE NOT EXISTS (SELECT 1 FROM protocol_documents WHERE experiment_id='exp-demo')",
        (json.dumps(json.loads(path.read_text())),))


@lru_cache(maxsize=1)
def get_db() -> Database:
    """Process-wide DB handle; schema is initialised on first use (also on serverless cold start)."""
    return make_database()
