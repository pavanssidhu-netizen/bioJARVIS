"""Push new telemetry spans from the app DB (Turso if configured, else local SQLite) to local Langfuse.

    .venv/bin/python scripts/langfuse_sync.py            # once
    .venv/bin/python scripts/langfuse_sync.py --watch    # every 10 s
    .venv/bin/python scripts/langfuse_sync.py --dry-run  # print what would be sent

Needs LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY in .env (Langfuse UI -> Project -> Settings -> API keys).
Cursor kept in data/langfuse_sync_cursor.json so spans are sent once.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.db import get_db  # noqa: E402
from backend.app.orchestration.langfuse_export import LangfuseConfig, send, spans_to_events  # noqa: E402

CURSOR = ROOT / "data" / "langfuse_sync_cursor.json"


def load_cursor() -> str:
    try:
        return json.loads(CURSOR.read_text())["start_time"]
    except (FileNotFoundError, KeyError, ValueError):
        return ""


def sync_once(dry_run: bool = False) -> int:
    db, cfg = get_db(), LangfuseConfig()
    since = load_cursor()
    # Overlap-safe cursor (>=): Langfuse upserts by id, so re-sending the boundary span is harmless.
    rows = db.execute("SELECT * FROM telemetry_spans WHERE start_time >= ? ORDER BY start_time LIMIT 2000", (since,))
    if not rows:
        return 0
    events = spans_to_events(rows, cfg.environment)
    if dry_run:
        print(json.dumps(events[:3], indent=2)[:3000], f"\n... {len(events)} events from {len(rows)} spans")
        return len(rows)
    res = send(events, cfg)
    CURSOR.parent.mkdir(parents=True, exist_ok=True)
    CURSOR.write_text(json.dumps({"start_time": rows[-1]["start_time"]}))
    print(f"[langfuse] {len(rows)} spans -> {res['sent']} events ok, {res['errors']} errors ({db.label} -> {cfg.host})")
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.dry_run and not LangfuseConfig().configured:
        sys.exit("Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env (Langfuse UI -> Settings -> API keys).")
    while True:
        sync_once(a.dry_run)
        if not a.watch:
            break
        time.sleep(10)
