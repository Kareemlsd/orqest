"""Execution-accuracy evaluation for Spider candidate SQL.

A candidate SQL string PASSES iff executing it on the relevant SQLite
DB returns a row set that matches the gold SQL's row set. Following
Spider's official convention, we treat row order as *unordered* by
default (since most questions don't specify ordering) and fall back to
ordered comparison when the gold query contains ``ORDER BY``.

This is intentionally simpler than Spider's official ``evaluation.py``
script, which also rewards partial-component matches (e.g., correct
SELECT clause + wrong WHERE). We use strict execution accuracy because
(a) it's the most defensible single metric and (b) it's what the
2024-2025 SOTA papers (DIN-SQL, MARS-SQL) compare on.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .dataset import db_path

# Wall-clock cap on a single SQL execution. Spider DBs are tiny; if a query
# takes longer it's almost certainly a runaway join — kill and mark as error.
_EXEC_TIMEOUT_S = 10.0
_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


class EvalOutcome(BaseModel):
    """One (candidate, gold) execution-accuracy verdict."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    candidate_rows: int = Field(ge=0)
    gold_rows: int = Field(ge=0)
    candidate_error: str | None = None
    gold_error: str | None = None
    duration_ms: float = Field(ge=0.0)
    order_sensitive: bool
    """True when the gold SQL contains ORDER BY → comparison is order-strict."""


class BaselineRunResult(BaseModel):
    """One question's full baseline-run record (per-question persisted JSON shape)."""

    model_config = ConfigDict(frozen=True)

    db_id: str
    question: str
    gold_sql: str
    candidate_sql: str
    outcome: EvalOutcome
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0


def execute_sql(
    db_id: str,
    sql: str,
    *,
    timeout_s: float = _EXEC_TIMEOUT_S,
) -> tuple[list[tuple[Any, ...]] | None, str | None]:
    """Execute *sql* on the named DB.

    Returns ``(rows, None)`` on success, ``(None, error_message)`` on failure.
    Never raises — every error path becomes a typed return.
    """
    path = db_path(db_id)
    if not path.exists():
        return None, f"db not found: {path}"
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout_s)
        con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    except sqlite3.Error as exc:
        return None, f"connect failed: {exc}"
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        return rows, None
    except sqlite3.Error as exc:
        return None, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass


def rows_match(
    a: Iterable[tuple[Any, ...]] | None,
    b: Iterable[tuple[Any, ...]] | None,
    *,
    order_sensitive: bool,
) -> bool:
    """Compare two row sets for execution-accuracy.

    Order-sensitive: compare list-equality. Order-insensitive: compare
    multiset equality (sorted by canonicalized string repr).
    """
    if a is None or b is None:
        return False
    la = list(a)
    lb = list(b)
    if len(la) != len(lb):
        return False
    if order_sensitive:
        return la == lb
    # Canonical sort so e.g. (None, 1) and (1, None) don't collide
    def key(row: tuple[Any, ...]) -> tuple[str, ...]:
        return tuple(repr(v) for v in row)

    return sorted(la, key=key) == sorted(lb, key=key)


def evaluate_candidate(
    db_id: str,
    candidate_sql: str,
    gold_sql: str,
    *,
    timeout_s: float = _EXEC_TIMEOUT_S,
) -> EvalOutcome:
    """Run both candidate and gold; return :class:`EvalOutcome`.

    Order-sensitivity is derived from the gold query's ORDER BY presence.
    """
    order_sensitive = bool(_ORDER_BY_RE.search(gold_sql))
    start = time.monotonic()
    cand_rows, cand_err = execute_sql(db_id, candidate_sql, timeout_s=timeout_s)
    gold_rows, gold_err = execute_sql(db_id, gold_sql, timeout_s=timeout_s)
    elapsed = (time.monotonic() - start) * 1000.0

    if gold_err:
        # Gold should always execute; if not, the DB is broken or the gold
        # is dirty. Mark as fail but log both sides for diagnosis.
        passed = False
    elif cand_err:
        passed = False
    else:
        passed = rows_match(
            cand_rows, gold_rows, order_sensitive=order_sensitive
        )

    return EvalOutcome(
        passed=passed,
        candidate_rows=len(cand_rows) if cand_rows is not None else 0,
        gold_rows=len(gold_rows) if gold_rows is not None else 0,
        candidate_error=cand_err,
        gold_error=gold_err,
        duration_ms=elapsed,
        order_sensitive=order_sensitive,
    )


__all__ = [
    "BaselineRunResult",
    "EvalOutcome",
    "evaluate_candidate",
    "execute_sql",
    "rows_match",
]
