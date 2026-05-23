"""BIRD-dev dataset loader, stratified sampler, schema extraction.

BIRD's official dev distribution (from
https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip) lays out as:

    data/bird/dev.json                          # questions array
    data/bird/dev_databases/<db_id>/<db_id>.sqlite
    data/bird/dev_databases/<db_id>/database_description/*.csv  # col docs

The question record differs from Spider:

    {
      "question_id": int,
      "db_id": str,
      "question": str,
      "evidence": str | null,  # natural-language hint
      "SQL": str,              # gold SQL (note capitalization)
      "difficulty": "simple" | "moderate" | "challenging"
    }

We carry ``evidence`` through to the agent prompt because BIRD was designed
around it — questions are intentionally underspecified without it.
"""
from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "bird"
DEV_JSON = DATA_DIR / "dev.json"
DB_DIR = DATA_DIR / "dev_databases"

Difficulty = Literal["simple", "moderate", "challenging"]


class BIRDQuestion(BaseModel):
    """One BIRD-dev example."""

    model_config = ConfigDict(frozen=True)

    question_id: int
    db_id: str
    question: str
    evidence: str | None = None
    SQL: str
    difficulty: Difficulty | str = "moderate"

    @property
    def query(self) -> str:
        """Spider-compatible alias for the gold SQL."""
        return self.SQL


def load_dev() -> list[BIRDQuestion]:
    """Load all BIRD-dev questions. Raises FileNotFoundError if not extracted."""
    if not DEV_JSON.exists():
        raise FileNotFoundError(
            f"{DEV_JSON} missing — extract data/bird/dev.zip first "
            "(see scripts/download_bird.py)."
        )
    raw = json.loads(DEV_JSON.read_text())
    return [BIRDQuestion(**r) for r in raw]


def stratified_sample(
    questions: Iterable[BIRDQuestion],
    *,
    n: int,
    seed: int = 42,
    by: str = "db_id",
) -> list[BIRDQuestion]:
    """Sample *n* questions stratified by ``db_id`` (or ``difficulty``).

    BIRD-dev has 11 DBs and 3 difficulty buckets; stratifying by DB
    ensures schema diversity (the harder property). Stratifying by
    difficulty trades that for guaranteed difficulty spread.
    """
    if by not in ("db_id", "difficulty"):
        raise ValueError("by must be 'db_id' or 'difficulty'")

    by_key: dict[str, list[BIRDQuestion]] = defaultdict(list)
    for q in questions:
        key = getattr(q, by)
        by_key[str(key)].append(q)

    total = sum(len(v) for v in by_key.values())
    if n >= total:
        return list(questions)

    rng = random.Random(seed)
    per_key = {
        k: max(1, round(len(qs) * n / total)) for k, qs in by_key.items()
    }
    while sum(per_key.values()) > n:
        biggest = max(per_key, key=lambda k: per_key[k])
        per_key[biggest] -= 1
    while sum(per_key.values()) < n:
        options = sorted(
            per_key, key=lambda k: len(by_key[k]) - per_key[k], reverse=True
        )
        for opt in options:
            if per_key[opt] < len(by_key[opt]):
                per_key[opt] += 1
                break
        else:
            break

    out: list[BIRDQuestion] = []
    for key, k in per_key.items():
        picks = rng.sample(by_key[key], k=min(k, len(by_key[key])))
        out.extend(picks)
    rng.shuffle(out)
    return out


def db_path(db_id: str) -> Path:
    """SQLite path for *db_id*."""
    return DB_DIR / db_id / f"{db_id}.sqlite"


def extract_schema_ddl(db_id: str, *, with_samples: bool = False) -> str:
    """Return CREATE-statement-style schema text from sqlite_master.

    BIRD doesn't ship a ``schema.sql`` per DB the way prem-research/spider
    does, so we always introspect from sqlite_master. ``with_samples=True``
    appends a short ``-- sample <table>: ...`` line per table for value
    disambiguation.
    """
    ddl = _introspect_sqlite_master(db_id)
    if not with_samples:
        return ddl
    samples = _sample_rows(db_id, n=3)
    return ddl + ("\n\n" + samples if samples else "")


def _introspect_sqlite_master(db_id: str) -> str:
    path = db_path(db_id)
    if not path.exists():
        return f"-- ERROR: db not found at {path}"
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return ";\n".join(r[0] for r in rows if r[0]) + ";"
    finally:
        con.close()


def _sample_rows(db_id: str, *, n: int = 3) -> str:
    path = db_path(db_id)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        out: list[str] = []
        for t in tables:
            try:
                rows = con.execute(f'SELECT * FROM "{t}" LIMIT {n}').fetchall()
            except sqlite3.Error:
                continue
            if rows:
                out.append(f"-- sample {t}: " + " | ".join(repr(r) for r in rows))
        return "\n".join(out)
    finally:
        con.close()


__all__ = [
    "BIRDQuestion",
    "DATA_DIR",
    "DB_DIR",
    "DEV_JSON",
    "Difficulty",
    "db_path",
    "extract_schema_ddl",
    "load_dev",
    "stratified_sample",
]
