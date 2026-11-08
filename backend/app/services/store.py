"""Recording + event ingestion engine. The backend is the single authority on recording state."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..config import get_settings
from ..contracts import EventIn, Experiment, ObservationEvent, RecordingSession, Review, ReviewIn
from ..db.database import Database


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: Optional[dict] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.detail = status, code, message, detail


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class Store:
    def __init__(self, db: Database):
        self.db = db
        self.settings = get_settings()

    # ---------------- experiments ----------------
    def list_experiments(self) -> list[Experiment]:
        return [Experiment(**r) for r in self.db.execute("SELECT * FROM experiments ORDER BY created_at DESC")]

    def get_experiment(self, exp_id: str) -> Experiment:
        rows = self.db.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,))
        if not rows:
            raise ApiError(404, "experiment_not_found", f"Experiment {exp_id} does not exist")
        return Experiment(**rows[0])

    def create_experiment(self, name: str) -> Experiment:
        exp_id = "exp-" + uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO experiments (id, name, created_at, status) VALUES (?, ?, ?, 'active')",
            (exp_id, name, now_iso()),
        )
        return self.get_experiment(exp_id)

    # ---------------- recording sessions ----------------
    def _session_row(self, session_id: str) -> dict:
        rows = self.db.execute("SELECT * FROM recording_sessions WHERE id = ?", (session_id,))
        if not rows:
            raise ApiError(404, "recording_not_found", f"Recording session {session_id} does not exist")
        return rows[0]

    def _reconcile(self, row: dict) -> dict:
        """Expire an 'active' session whose client stopped heartbeating (crash, closed tab, lost network)."""
        if row["status"] != "active":
            return row
        deadline = _parse(row["last_heartbeat_at"]) + timedelta(seconds=self.settings.heartbeat_timeout_s)
        if datetime.now(timezone.utc) > deadline:
            self.db.execute(
                "UPDATE recording_sessions SET status='expired', stopped_at=?, stop_reason='heartbeat_timeout' "
                "WHERE id=? AND status='active'",
                (row["last_heartbeat_at"], row["id"]),
            )
            self.purge_frames(row["id"])
            row = self._session_row(row["id"])
        return row

    def _to_session(self, row: dict) -> RecordingSession:
        n = self.db.execute("SELECT COUNT(*) AS n FROM observation_events WHERE session_id = ?", (row["id"],))[0]["n"]
        return RecordingSession(**row, event_count=n)

    def get_recording(self, session_id: str) -> RecordingSession:
        return self._to_session(self._reconcile(self._session_row(session_id)))

    def active_recording(self, experiment_id: str) -> Optional[RecordingSession]:
        for row in self.db.execute(
            "SELECT * FROM recording_sessions WHERE experiment_id=? AND status='active' ORDER BY started_at DESC",
            (experiment_id,),
        ):
            row = self._reconcile(row)
            if row["status"] == "active":
                return self._to_session(row)
        return None

    def start_recording(self, experiment_id: str) -> RecordingSession:
        self.get_experiment(experiment_id)
        existing = self.active_recording(experiment_id)
        if existing:  # idempotent: one active recording per experiment
            return self.heartbeat(existing.id)
        sid = "rec-" + uuid.uuid4().hex[:12]
        ts = now_iso()
        self.db.execute(
            "INSERT INTO recording_sessions (id, experiment_id, started_at, status, last_heartbeat_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (sid, experiment_id, ts, ts),
        )
        return self.get_recording(sid)

    def stop_recording(self, session_id: str, reason: str = "user_stopped") -> RecordingSession:
        row = self._reconcile(self._session_row(session_id))
        if row["status"] == "active":
            self.db.execute(
                "UPDATE recording_sessions SET status='stopped', stopped_at=?, stop_reason=? WHERE id=? AND status='active'",
                (now_iso(), reason, session_id),
            )
            self.purge_frames(session_id)  # retained video frames live only for the session
        return self.get_recording(session_id)

    def heartbeat(self, session_id: str) -> RecordingSession:
        row = self._reconcile(self._session_row(session_id))
        if row["status"] != "active":
            raise ApiError(409, "recording_inactive", "Recording is not active", {"status": row["status"]})
        self.db.execute("UPDATE recording_sessions SET last_heartbeat_at=? WHERE id=?", (now_iso(), session_id))
        return self.get_recording(session_id)

    # ---------------- events ----------------
    def _event_from_row(self, row: dict, with_reviews: bool = True) -> ObservationEvent:
        reviews = self.reviews_for(row["id"]) if with_reviews else []
        status = reviews[-1].action if reviews else "pending"
        status = {"accept": "accepted", "dispute": "disputed", "correct": "corrected", "reject": "rejected"}.get(status, status)
        return ObservationEvent(
            id=row["id"], session_id=row["session_id"], experiment_id=row["experiment_id"],
            sequence_number=row["sequence_number"], timestamp=row["timestamp"],
            source_modality=row["source_modality"], event_type=row["event_type"],
            payload=json.loads(row["payload_json"]), model_name=row["model_name"], status=row["status"],
            idempotency_key=row["idempotency_key"], source_event_id=row["source_event_id"],
            review_status=status, reviews=reviews,
        )

    def get_event(self, event_id: str) -> ObservationEvent:
        rows = self.db.execute("SELECT * FROM observation_events WHERE id = ?", (event_id,))
        if not rows:
            raise ApiError(404, "observation_not_found", f"Observation {event_id} does not exist")
        return self._event_from_row(rows[0])

    def _by_idempotency(self, key: str) -> Optional[ObservationEvent]:
        rows = self.db.execute("SELECT * FROM observation_events WHERE idempotency_key = ?", (key,))
        return self._event_from_row(rows[0]) if rows else None

    def _insert_event(self, *, session_id: Optional[str], experiment_id: str, modality: str, event_type: str,
                      payload: dict, model_name: Optional[str], idem: str, source_event_id: Optional[str]) -> ObservationEvent:
        eid = "evt-" + uuid.uuid4().hex
        payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if len(payload_json) > 64_000:
            raise ApiError(413, "payload_too_large", "Event payload exceeds 64 KB")
        for _ in range(5):  # retry on the (rare) concurrent sequence-number collision
            try:
                # Single statement => sequence allocation and insert are atomic in SQLite/libSQL.
                self.db.execute(
                    "INSERT INTO observation_events (id, session_id, experiment_id, sequence_number, timestamp, "
                    "source_modality, event_type, payload_json, model_name, status, idempotency_key, source_event_id) "
                    "SELECT ?, ?, ?, COALESCE(MAX(sequence_number), 0) + 1, ?, ?, ?, ?, ?, 'persisted', ?, ? "
                    "FROM observation_events WHERE experiment_id = ?",
                    (eid, session_id, experiment_id, now_iso(), modality, event_type, payload_json, model_name,
                     idem, source_event_id, experiment_id),
                )
                return self.get_event(eid)
            except sqlite3.IntegrityError as e:
                if "idempotency_key" in str(e):
                    raise
        raise ApiError(503, "sequence_contention", "Could not allocate a sequence number; retry")

    def ingest(self, ev: EventIn) -> tuple[ObservationEvent, bool]:
        """Validate session -> check recording -> dedupe -> persist (committed) -> return. (event, duplicate)."""
        dup = self._by_idempotency(ev.idempotency_key)
        if dup:
            return dup, True
        session = self.get_recording(ev.session_id)
        if session.experiment_id != ev.experiment_id:
            raise ApiError(400, "session_experiment_mismatch", "Session does not belong to this experiment")
        if session.status != "active":
            raise ApiError(409, "recording_inactive", "Recording is not active; nothing was saved",
                           {"session_status": session.status})
        if ev.source_event_id:
            self.get_event(ev.source_event_id)
        try:
            event = self._insert_event(
                session_id=ev.session_id, experiment_id=ev.experiment_id, modality=ev.source_modality,
                event_type=ev.event_type, payload=ev.payload, model_name=ev.model_name,
                idem=ev.idempotency_key, source_event_id=ev.source_event_id,
            )
        except sqlite3.IntegrityError:  # lost an idempotency race to a concurrent retry
            dup = self._by_idempotency(ev.idempotency_key)
            if dup:
                return dup, True
            raise
        # Any accepted event also counts as liveness for the session.
        self.db.execute("UPDATE recording_sessions SET last_heartbeat_at=? WHERE id=?", (now_iso(), ev.session_id))
        return event, False

    def list_events(self, experiment_id: Optional[str] = None, after_seq: int = 0, limit: int = 200,
                    event_type: Optional[str] = None, modality: Optional[str] = None) -> list[ObservationEvent]:
        sql, params = "SELECT * FROM observation_events WHERE 1=1", []
        if experiment_id:
            sql += " AND experiment_id = ?"; params.append(experiment_id)
        if after_seq:
            sql += " AND sequence_number > ?"; params.append(after_seq)
        if event_type:
            sql += " AND event_type = ?"; params.append(event_type)
        if modality:
            sql += " AND source_modality = ?"; params.append(modality)
        sql += " ORDER BY experiment_id, sequence_number LIMIT ?"; params.append(max(1, min(limit, 500)))
        rows = self.db.execute(sql, params)
        reviews = self._reviews_bulk([r["id"] for r in rows])
        out = []
        for r in rows:
            e = self._event_from_row(r, with_reviews=False)
            rv = reviews.get(r["id"], [])
            if rv:
                last = rv[-1].action
                e.review_status = {"accept": "accepted", "dispute": "disputed", "correct": "corrected", "reject": "rejected"}[last]
                e.reviews = rv
            out.append(e)
        return out

    def last_sequence(self, experiment_id: str) -> int:
        return self.db.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) AS s FROM observation_events WHERE experiment_id = ?",
            (experiment_id,))[0]["s"]

    def last_write(self) -> Optional[str]:
        return self.db.execute("SELECT MAX(timestamp) AS t FROM observation_events")[0]["t"]

    # ---------------- reviews ----------------
    def _review_from_row(self, r: dict) -> Review:
        return Review(id=r["id"], observation_id=r["observation_id"], action=r["action"],
                      correction=json.loads(r["correction_json"]) if r["correction_json"] else None,
                      reviewer=r["reviewer"], timestamp=r["timestamp"])

    def reviews_for(self, obs_id: str) -> list[Review]:
        return [self._review_from_row(r) for r in self.db.execute(
            "SELECT * FROM observation_reviews WHERE observation_id = ? ORDER BY timestamp, rowid", (obs_id,))]

    def _reviews_bulk(self, ids: list[str]) -> dict[str, list[Review]]:
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        out: dict[str, list[Review]] = {}
        for r in self.db.execute(
                f"SELECT * FROM observation_reviews WHERE observation_id IN ({q}) ORDER BY timestamp, rowid", ids):
            out.setdefault(r["observation_id"], []).append(self._review_from_row(r))
        return out

    def review(self, obs_id: str, body: ReviewIn) -> tuple[Review, Optional[ObservationEvent]]:
        original = self.get_event(obs_id)
        if body.action == "correct" and not body.correction:
            raise ApiError(422, "correction_required", "action=correct requires a correction object")
        correction_event = None
        if body.action == "correct":
            # Never overwrite: a correction is a NEW event linked to the original.
            correction_event = self._insert_event(
                session_id=original.session_id, experiment_id=original.experiment_id, modality="text",
                event_type="correction",
                payload={"corrects_event_id": obs_id, "correction": body.correction, "reviewer": body.reviewer},
                model_name=None, idem="corr-" + uuid.uuid4().hex, source_event_id=obs_id,
            )
        rid = "rev-" + uuid.uuid4().hex[:16]
        self.db.execute(
            "INSERT INTO observation_reviews (id, observation_id, action, correction_json, reviewer, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rid, obs_id, body.action, json.dumps(body.correction) if body.correction else None, body.reviewer, now_iso()),
        )
        rev = [r for r in self.reviews_for(obs_id) if r.id == rid][0]
        return rev, correction_event

    # ---------------- V2: live session state (active step/channel, voice-controlled tracking) ----------------
    def session_state(self, session_id: str) -> dict:
        self._session_row(session_id)
        rows = self.db.execute("SELECT * FROM session_state WHERE session_id=?", (session_id,))
        if not rows:
            return {"session_id": session_id, "active_step_id": None, "active_channel_id": None, "tracking": [],
                    "updated_at": None}
        r = rows[0]
        return {"session_id": session_id, "active_step_id": r["active_step_id"],
                "active_channel_id": r["active_channel_id"], "tracking": json.loads(r["tracking_json"] or "[]"),
                "updated_at": r["updated_at"]}

    def update_session_state(self, session_id: str, *, active_step_id: Optional[str] = None,
                             active_channel_id: Optional[str] = None, tracking: Optional[list] = None,
                             clear_channel: bool = False) -> dict:
        rec = self.get_recording(session_id)
        if rec.status != "active":
            raise ApiError(409, "recording_inactive", "Session state can only change during an active recording")
        cur = self.session_state(session_id)
        step = active_step_id if active_step_id is not None else cur["active_step_id"]
        chan = None if clear_channel else (active_channel_id if active_channel_id is not None else cur["active_channel_id"])
        trk = tracking if tracking is not None else cur["tracking"]
        self.db.execute(
            "INSERT INTO session_state (session_id, active_step_id, active_channel_id, tracking_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET active_step_id=excluded.active_step_id, "
            "active_channel_id=excluded.active_channel_id, tracking_json=excluded.tracking_json, "
            "updated_at=excluded.updated_at", (session_id, step, chan, json.dumps(trk), now_iso()))
        return self.session_state(session_id)

    def track(self, session_id: str, label: str, channel_id: Optional[str] = None, by: str = "user") -> dict:
        label = label.strip().lower()[:60]
        if not label:
            raise ApiError(422, "invalid_label", "label is required")
        trk = [t for t in self.session_state(session_id)["tracking"] if t["label"] != label]
        trk.append({"label": label, "channel_id": channel_id, "added_at": now_iso(), "added_by": by})
        return self.update_session_state(session_id, tracking=trk[-12:])

    def untrack(self, session_id: str, label: str) -> dict:
        label = label.strip().lower()
        cur = self.session_state(session_id)["tracking"]
        trk = [t for t in cur if t["label"] != label] if label not in ("all", "*") else []
        if len(trk) == len(cur) and label not in ("all", "*"):
            raise ApiError(404, "not_tracked", f"'{label}' is not being tracked")
        return self.update_session_state(session_id, tracking=trk)

    # ---------------- V2: session frame retention (kept only until the session ends) ----------------
    def store_frames(self, session_id: str, experiment_id: str, frames: list[tuple[str, bytes, str, str]]) -> list[str]:
        """frames: (captured_at_iso, data, mime, sha256). Only for ACTIVE sessions."""
        if self.get_recording(session_id).status != "active":
            return []
        ids = []
        for ts, data, mime, sha in frames:
            fid = "frm-" + uuid.uuid4().hex[:16]
            self.db.execute("INSERT INTO session_frames (id, session_id, experiment_id, captured_at, mime_type, sha256, "
                            "bytes, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (fid, session_id, experiment_id, ts, mime, sha, len(data), data))
            ids.append(fid)
        return ids

    def list_frames(self, session_id: str, start: Optional[str] = None, end: Optional[str] = None,
                    limit: int = 500) -> list[dict]:
        sql, p = "SELECT id, captured_at, mime_type, sha256, bytes FROM session_frames WHERE session_id=?", [session_id]
        if start:
            sql += " AND captured_at >= ?"; p.append(start)
        if end:
            sql += " AND captured_at <= ?"; p.append(end)
        return self.db.execute(sql + " ORDER BY captured_at LIMIT ?", [*p, limit])

    def get_frame(self, session_id: str, frame_id: str) -> dict:
        rows = self.db.execute("SELECT * FROM session_frames WHERE session_id=? AND id=?", (session_id, frame_id))
        if not rows:
            raise ApiError(404, "frame_not_found", "Frame not found (frames are purged when the session ends)")
        return rows[0]

    def purge_frames(self, session_id: str) -> int:
        n = self.db.execute("SELECT COUNT(*) n FROM session_frames WHERE session_id=?", (session_id,))[0]["n"]
        if n:
            self.db.execute("DELETE FROM session_frames WHERE session_id=?", (session_id,))
        return n

    # ---------------- V2: history ----------------
    def experiment_sessions(self, experiment_id: str) -> list[dict]:
        self.get_experiment(experiment_id)
        rows = self.db.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM observation_events e WHERE e.session_id=s.id) AS event_count, "
            "(SELECT COUNT(*) FROM observation_events e WHERE e.session_id=s.id AND e.event_type='reconciliation' "
            " AND json_extract(e.payload_json,'$.requires_human_approval')=1) AS flagged_count "
            "FROM recording_sessions s WHERE s.experiment_id=? ORDER BY s.started_at DESC", (experiment_id,))
        for r in rows:
            self._reconcile(r)
        return rows

    def media_hashes(self, experiment_id: str) -> int:
        return self.db.execute("SELECT COUNT(*) n FROM media_assets WHERE experiment_id=?", (experiment_id,))[0]["n"]

    # ---------------- media provenance ----------------
    def record_media_hash(self, experiment_id: str, sha256: str, mime: str, source_event_id: str) -> None:
        """Phase 1 stores only the hash/mime of an analysed image (file_path NULL = raw bytes not kept)."""
        self.db.execute(
            "INSERT INTO media_assets (id, experiment_id, file_path, sha256_hash, mime_type, created_at, source_event_id) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?)",
            ("med-" + uuid.uuid4().hex[:16], experiment_id, sha256, mime, now_iso(), source_event_id),
        )

    def experiment_context(self, experiment_id: str) -> dict[str, Any]:
        exp = self.get_experiment(experiment_id)
        proto = self.get_protocol(experiment_id)
        n = self.db.execute("SELECT COUNT(*) AS n FROM observation_events WHERE experiment_id=?", (experiment_id,))[0]["n"]
        return {"experiment": exp.model_dump(), "observation_count": n,
                "protocol": ({"version": proto.version, "content": proto.content.model_dump()} if proto else None)}

    # ---------------- protocols (versioned, append-only) ----------------
    def get_protocol(self, experiment_id: str, version: Optional[int] = None):
        from ..contracts import ProtocolContent, ProtocolDocument
        sql = "SELECT * FROM protocol_documents WHERE experiment_id=?"
        params: list[Any] = [experiment_id]
        if version:
            sql += " AND version=?"; params.append(version)
        rows = self.db.execute(sql + " ORDER BY version DESC LIMIT 1", params)
        if not rows:
            return None
        r = rows[0]
        return ProtocolDocument(id=r["id"], experiment_id=r["experiment_id"], version=r["version"],
                                content=ProtocolContent.model_validate_json(r["content_json"]), created_at=r["created_at"])

    def put_protocol(self, experiment_id: str, content) -> Any:
        """Store a NEW version; earlier versions are kept for provenance."""
        self.get_experiment(experiment_id)
        for _ in range(3):
            v = self.db.execute("SELECT COALESCE(MAX(version),0)+1 AS v FROM protocol_documents WHERE experiment_id=?",
                                (experiment_id,))[0]["v"]
            body = content.model_copy(update={"version": v}).model_dump_json()
            pid = "prot-" + uuid.uuid4().hex[:12]
            try:
                self.db.execute(
                    "INSERT INTO protocol_documents (id, experiment_id, version, content_json, created_at) "
                    "SELECT ?, ?, ?, ?, ? WHERE NOT EXISTS "
                    "(SELECT 1 FROM protocol_documents WHERE experiment_id=? AND version=?)",
                    (pid, experiment_id, v, body, now_iso(), experiment_id, v))
            except sqlite3.IntegrityError:
                continue
            got = self.get_protocol(experiment_id, v)
            if got and got.id == pid:
                return got
        raise ApiError(503, "protocol_version_contention", "Concurrent protocol update; retry")

    # ---------------- UI actions (content-free interaction log) ----------------
    def record_ui_actions(self, batch) -> int:
        self.get_experiment(batch.experiment_id)
        from ..orchestration.telemetry import session_id_var
        n = 0
        for a in batch.actions:
            detail = {k: v for k, v in a.detail.items() if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 80}
            self.db.execute(
                "INSERT INTO ui_actions (id, experiment_id, client_session, recording_session_id, action, source, "
                "detail_json, client_timestamp, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ui-" + uuid.uuid4().hex[:16], batch.experiment_id, session_id_var.get() or None,
                 batch.recording_session_id, a.action, a.source, json.dumps(detail) if detail else None,
                 a.client_timestamp, now_iso()))
            n += 1
        return n

    def recent_ui_actions(self, experiment_id: str, limit: int = 50) -> list[dict]:
        rows = self.db.execute("SELECT action, source, detail_json, timestamp FROM ui_actions WHERE experiment_id=? "
                               "ORDER BY timestamp DESC LIMIT ?", (experiment_id, limit))
        return [{**r, "detail": json.loads(r.pop("detail_json") or "{}")} for r in reversed(rows)]
