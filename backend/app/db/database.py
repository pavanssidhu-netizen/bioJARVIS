"""Minimal SQL access layer with two interchangeable backends.

* SqliteDatabase - a local SQLite file (dev, tests, laptop demos). WAL mode enabled.
* TursoDatabase  - Turso/libSQL over its HTTP pipeline API (used when deployed to Vercel,
                   where serverless functions have no persistent disk).

Both speak the same SQLite dialect, so the schema and queries are identical.
Each `execute` is a single auto-committed statement: when it returns, the write is durable.
"""
from __future__ import annotations

import base64
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol, Sequence

import httpx

Row = dict[str, Any]


class Database(Protocol):
    label: str

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[Row]: ...

    def executescript(self, statements: Sequence[str]) -> None: ...


class SqliteDatabase:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.label = str(path)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def executescript(self, statements: Sequence[str]) -> None:
        with self._lock:
            for s in statements:
                self._conn.execute(s)

    def close(self) -> None:
        self._conn.close()


class TursoDatabase:
    def __init__(self, url: str, token: str):
        host = url.split("://", 1)[-1].rstrip("/")
        self.label = "turso:" + host
        self._endpoint = f"https://{host}/v2/pipeline"
        self._client = httpx.Client(timeout=15.0, headers={"Authorization": f"Bearer {token}"})

    @staticmethod
    def _arg(v: Any) -> dict:
        if v is None:
            return {"type": "null"}
        if isinstance(v, bool):
            return {"type": "integer", "value": str(int(v))}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": v}
        if isinstance(v, bytes):
            return {"type": "blob", "base64": base64.b64encode(v).decode()}
        return {"type": "text", "value": str(v)}

    @staticmethod
    def _val(cell: dict) -> Any:
        t = cell.get("type")
        if t == "null":
            return None
        if t == "integer":
            return int(cell["value"])
        if t == "float":
            return float(cell["value"])
        if t == "blob":
            return base64.b64decode(cell["base64"])
        return cell.get("value")

    def _pipeline(self, stmts: Sequence[tuple[str, Sequence[Any]]]) -> list[list[Row]]:
        reqs = [{"type": "execute", "stmt": {"sql": s, "args": [self._arg(a) for a in p]}} for s, p in stmts]
        reqs.append({"type": "close"})
        resp = self._client.post(self._endpoint, json={"requests": reqs})
        resp.raise_for_status()
        out: list[list[Row]] = []
        for r in resp.json()["results"][: len(stmts)]:
            if r["type"] == "error":
                msg = r["error"].get("message", "unknown")
                if "UNIQUE constraint failed" in msg:
                    raise sqlite3.IntegrityError(msg)
                raise RuntimeError(f"Turso error: {msg}")
            res = r["response"]["result"]
            cols = [c["name"] for c in res["cols"]]
            out.append([dict(zip(cols, (self._val(c) for c in row))) for row in res["rows"]])
        return out

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        return self._pipeline([(sql, params)])[0]

    def executescript(self, statements: Sequence[str]) -> None:
        self._pipeline([(s, ()) for s in statements])
