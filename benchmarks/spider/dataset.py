"""Spider-dev dataset loader + stratified sampler + schema extraction.

The Spider 1.0 dev split contains 1034 (question, gold-SQL, db_id) triples
across 20 distinct SQLite databases. We persist the questions to
``data/spider/dev.json`` and the databases to ``data/spider/database/<db_id>/``
via :mod:`scripts.download_spider`.

Stratified sampling proportionally covers all 20 DBs so a benchmark run
exercises the schema diversity the topology needs to handle.
"""
from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "spider"
DEV_JSON = DATA_DIR / "dev.json"
DB_DIR = DATA_DIR / "database"


class SpiderQuestion(BaseModel):
    """One Spider example — question, db_id, gold SQL."""

    model_config = ConfigDict(frozen=True)

    db_id: str
    question: str
    query: str
    """The gold SQL query (Spider's published reference)."""


def load_dev() -> list[SpiderQuestion]:
    """Load all 1034 dev questions. Raises FileNotFoundError if not downloaded."""
    if not DEV_JSON.exists():
        raise FileNotFoundError(
            f"{DEV_JSON} missing — run `python scripts/download_spider.py` first."
        )
    raw = json.loads(DEV_JSON.read_text())
    return [SpiderQuestion(**r) for r in raw]


def stratified_sample(
    questions: Iterable[SpiderQuestion],
    *,
    n: int,
    seed: int = 42,
) -> list[SpiderQuestion]:
    """Sample *n* questions stratified by db_id.

    Each of Spider-dev's 20 DBs contributes proportionally to its share of
    the total. Within each DB, order is randomized by *seed*. Deterministic
    given the same (questions, n, seed) triple.
    """
    by_db: dict[str, list[SpiderQuestion]] = defaultdict(list)
    for q in questions:
        by_db[q.db_id].append(q)
    total = sum(len(v) for v in by_db.values())
    if n >= total:
        return list(questions)

    rng = random.Random(seed)
    # Allocate per-DB quota by share, rounding up so we don't under-sample.
    per_db = {
        db: max(1, round(len(qs) * n / total))
        for db, qs in by_db.items()
    }

    # Trim down: drop one from the largest quota until we hit n exactly.
    while sum(per_db.values()) > n:
        biggest = max(per_db, key=lambda k: per_db[k])
        per_db[biggest] -= 1
    while sum(per_db.values()) < n:
        smallest = min(per_db, key=lambda k: per_db[k])
        if per_db[smallest] < len(by_db[smallest]):
            per_db[smallest] += 1
        else:
            # Sorted by amount of headroom we still have
            options = sorted(
                per_db, key=lambda k: len(by_db[k]) - per_db[k], reverse=True
            )
            for opt in options:
                if per_db[opt] < len(by_db[opt]):
                    per_db[opt] += 1
                    break
            else:
                break

    out: list[SpiderQuestion] = []
    for db, k in per_db.items():
        picks = rng.sample(by_db[db], k=min(k, len(by_db[db])))
        out.extend(picks)
    rng.shuffle(out)
    return out


def db_path(db_id: str) -> Path:
    """Filesystem path to ``<db_id>.sqlite`` under ``data/spider/database``."""
    return DB_DIR / db_id / f"{db_id}.sqlite"


def extract_schema_ddl(db_id: str, *, with_samples: bool = False) -> str:
    """Return the schema as CREATE statements.

    Prefers the on-disk ``schema.sql`` (cleaner than ``sqlite_master`` —
    no auto-indexes, includes comments) when present. Falls back to
    introspecting ``sqlite_master`` otherwise.

    Args:
        db_id: Spider DB identifier.
        with_samples: When True, append a short ``-- sample: ...`` line per
            table with the first ~3 rows. Useful for value-disambiguation
            but doubles prompt size.
    """
    schema_file = DB_DIR / db_id / "schema.sql"
    ddl: str
    if schema_file.exists():
        ddl = schema_file.read_text()
    else:
        ddl = _introspect_sqlite_master(db_id)

    if not with_samples:
        return ddl

    samples = _sample_rows(db_id, n=3)
    if not samples:
        return ddl
    return ddl + "\n\n" + samples


def _introspect_sqlite_master(db_id: str) -> str:
    """Fallback schema extraction via SELECT sql FROM sqlite_master."""
    con = sqlite3.connect(db_path(db_id))
    try:
        rows = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return ";\n".join(r[0] for r in rows if r[0]) + ";"
    finally:
        con.close()


def _sample_rows(db_id: str, *, n: int = 3) -> str:
    """Concatenate sample rows per table as `-- sample [table]: (...)`."""
    con = sqlite3.connect(db_path(db_id))
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
    "DATA_DIR",
    "DB_DIR",
    "DEV_JSON",
    "SpiderQuestion",
    "db_path",
    "extract_schema_ddl",
    "load_dev",
    "stratified_sample",
]
