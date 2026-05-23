"""TopologyEvaluator subclass for BIRD execution-accuracy scoring.

The base :class:`TopologyEvaluator` already does the heavy lifting —
hydrates a candidate :data:`TopologySpec` into a runtime topology,
runs it on each gold example, and bundles up the result. We only
add:

1. ``score_fn`` — extracts the topology's ``final_sql`` and compares
   execution rows against the gold SQL.
2. :func:`bird_gold_examples` — converts a list of
   :class:`BIRDQuestion` into :class:`GoldExample` shapes carrying the
   :class:`SQLTaskState` input.

That's it. Everything else (minibatching, hydration errors as zero
accuracy, structural metrics ``n_agents`` / ``depth``) is inherited.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from orqest.agents.base_agent import BaseAgent
from .state import SQLTaskState, extract_final_sql
from ..dataset import (
    BIRDQuestion,
    db_path,
    extract_schema_ddl,
)
from ...spider.harness import rows_match
from orqest.optimization.evaluator import GoldExample
from orqest.optimization.topology import TopologyEvaluator
from orqest.orchestration.hydrate import CallableRegistry


def _execute(db_id: str, sql: str, timeout_s: float = 30.0):
    path = db_path(db_id)
    if not path.exists() or not sql.strip():
        return None, "missing db or empty sql"
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout_s)
        con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    except sqlite3.Error as exc:
        return None, f"connect failed: {exc}"
    try:
        return con.execute(sql).fetchall(), None
    except sqlite3.Error as exc:
        return None, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass


def _score_fn(
    output: Any, example: GoldExample[SQLTaskState, SQLTaskState]
) -> float:
    """Execution-accuracy: 1.0 if candidate rows match gold rows, else 0.0.

    Receives ``output`` already unpacked by
    :func:`orqest.optimization.topology.unpack_topology_output` (handles
    Parallel.merged / Loop.output indirections), so we just extract the
    final SQL string.
    """
    state = example.input
    gold_sql = (example.expected.final_sql or "").strip() if example.expected else ""
    if not gold_sql:
        return 0.0
    cand_sql = extract_final_sql(output)
    if not cand_sql:
        return 0.0
    cand_rows, cand_err = _execute(state.db_id, cand_sql)
    if cand_err:
        return 0.0
    gold_rows, gold_err = _execute(state.db_id, gold_sql)
    if gold_err:
        # Gold should always execute; if not, treat as 0 but log via raw
        return 0.0
    import re
    order_sensitive = bool(re.search(r"\border\s+by\b", gold_sql, re.IGNORECASE))
    return 1.0 if rows_match(
        cand_rows, gold_rows, order_sensitive=order_sensitive
    ) else 0.0


class BIRDTopologyEvaluator(TopologyEvaluator[SQLTaskState, SQLTaskState]):
    """:class:`TopologyEvaluator` wired with BIRD's execution-accuracy score_fn."""

    def __init__(
        self,
        *,
        callable_registry: CallableRegistry,
        agent_registry: dict[str, Callable[[], BaseAgent[Any, Any]]],
        topology_gene_name: str = "main",
    ) -> None:
        super().__init__(
            score_fn=_score_fn,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            topology_gene_name=topology_gene_name,
        )


def bird_gold_examples(
    questions: list[BIRDQuestion],
    *,
    with_samples: bool = False,
) -> list[GoldExample[SQLTaskState, SQLTaskState]]:
    """Convert BIRD questions into GoldExamples carrying :class:`SQLTaskState`.

    Each example's input is a fully-populated SQLTaskState (question +
    schema + evidence); the expected output is a SQLTaskState whose
    ``final_sql`` is the gold query — used by :func:`_score_fn` to know
    what to compare against.
    """
    examples: list[GoldExample[SQLTaskState, SQLTaskState]] = []
    for q in questions:
        schema = extract_schema_ddl(q.db_id, with_samples=with_samples)
        in_state = SQLTaskState(
            question=q.question,
            db_id=q.db_id,
            evidence=q.evidence,
            full_schema_ddl=schema,
        )
        gold_state = SQLTaskState(
            question=q.question,
            db_id=q.db_id,
            evidence=q.evidence,
            full_schema_ddl=schema,
            final_sql=q.SQL,
        )
        examples.append(
            GoldExample(
                input=in_state,
                expected=gold_state,
                id=str(q.question_id),
            )
        )
    return examples


__all__ = ["BIRDTopologyEvaluator", "bird_gold_examples"]
