import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "labmate_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{p}")
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("VERCEL_ENV", "")
    monkeypatch.setenv("SPECIALIST_PROVIDER", "none")  # tests never call Modal unless they opt in
    monkeypatch.setenv("MODAL_ENABLED", "false")
    from backend.app.db import get_db
    get_db.cache_clear()
    yield p
    get_db.cache_clear()


@pytest.fixture()
def client(db_path):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    return TestClient(app)


@pytest.fixture()
def has_key():
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set")
