"""Watch events arrive in the LABMATE database from a terminal (local SQLite or Turso, per .env).

    .venv/bin/python scripts/watch_db.py [experiment_id]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.db import get_db  # noqa: E402

exp = sys.argv[1] if len(sys.argv) > 1 else "exp-demo"
db = get_db()
print(f"Watching {db.label} experiment={exp}  (Ctrl+C to stop)")
last = db.execute("SELECT COALESCE(MAX(sequence_number),0) s FROM observation_events WHERE experiment_id=?", (exp,))[0]["s"]
last = max(0, last - 10)
while True:
    for r in db.execute("SELECT * FROM observation_events WHERE experiment_id=? AND sequence_number>? "
                        "ORDER BY sequence_number", (exp, last)):
        last = r["sequence_number"]
        p = json.loads(r["payload_json"])
        if r["event_type"] == "perception":
            summary = p.get("scene_summary", "") + " | " + ", ".join(
                f"{a['action']}x{a['count']}" for a in p.get("actions", [])) 
        else:
            summary = p.get("text") or p.get("summary") or p.get("description") or json.dumps(p)[:120]
        print(f"#{r['sequence_number']:<5} {r['timestamp'][11:19]} {r['event_type']:<22} {r['source_modality']:<7} {summary[:110]}")
    rec = db.execute("SELECT id, status FROM recording_sessions WHERE experiment_id=? ORDER BY started_at DESC LIMIT 1", (exp,))
    sys.stdout.write(f"\r  recording: {rec[0]['status'] if rec else 'none'}   ")
    sys.stdout.flush()
    time.sleep(1.5)
