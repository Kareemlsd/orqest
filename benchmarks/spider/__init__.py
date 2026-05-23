"""Text-to-SQL benchmark on the Spider 1.0 dev split.

This is the v1 validation target for Orqest's MAS-synthesis thesis
(see ``.claude/plans/ORQEST_VALIDATION_DECISIONS_2026-05-15.md``).

Submodules:

* :mod:`.dataset` — load dev questions, stratified sampling, schema extraction.
* :mod:`.harness` — execution-accuracy comparator on local SQLite.
* :mod:`.baseline` — single-CoT agent (the floor we compare against).
"""

from .dataset import (
    SpiderQuestion,
    extract_schema_ddl,
    load_dev,
    stratified_sample,
)
from .harness import (
    BaselineRunResult,
    EvalOutcome,
    evaluate_candidate,
    execute_sql,
    rows_match,
)

__all__ = [
    "BaselineRunResult",
    "EvalOutcome",
    "SpiderQuestion",
    "evaluate_candidate",
    "execute_sql",
    "extract_schema_ddl",
    "load_dev",
    "rows_match",
    "stratified_sample",
]
