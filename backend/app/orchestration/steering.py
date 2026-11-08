"""Steering documents: markdown policy files composed into model prompts per role.

Files live in backend/steering/*.md with a tiny front matter:

    ---
    id: lab-safety
    applies_to: [live, query]
    priority: 10
    ---
    text...

Science teammates edit these (no code changes). Lower priority number = earlier in the prompt.
`compose(role)` returns the text plus a short content hash recorded in telemetry as the steering version.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

STEERING_DIR = Path(__file__).resolve().parents[2] / "steering"


@dataclass(frozen=True)
class SteeringDoc:
    id: str
    applies_to: tuple[str, ...]
    priority: int
    text: str


def _parse(path: Path) -> SteeringDoc:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    body = raw
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    applies = tuple(x.strip() for x in meta.get("applies_to", "[live]").strip("[]").split(",") if x.strip())
    return SteeringDoc(id=meta.get("id", path.stem), applies_to=applies, priority=int(meta.get("priority", 50)),
                       text=body.strip())


@lru_cache(maxsize=1)
def load_all() -> tuple[SteeringDoc, ...]:
    if not STEERING_DIR.is_dir():
        return ()
    return tuple(sorted((_parse(p) for p in STEERING_DIR.glob("*.md")), key=lambda d: (d.priority, d.id)))


def compose(role: str) -> tuple[str, str]:
    docs = [d for d in load_all() if role in d.applies_to or "all" in d.applies_to]
    text = "\n\n".join(f"## {d.id}\n{d.text}" for d in docs)
    return text, hashlib.sha256(text.encode()).hexdigest()[:10]


def list_docs() -> list[dict]:
    return [{"id": d.id, "applies_to": list(d.applies_to), "priority": d.priority, "chars": len(d.text)}
            for d in load_all()]
