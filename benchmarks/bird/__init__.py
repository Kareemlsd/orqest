"""Text-to-SQL benchmark on BIRD-dev.

The pivot from Spider to BIRD followed the 2026-05-15 baseline finding:
DeepSeek V3.2 + vanilla single-CoT hits 86% on Spider-dev — matching
DIN-SQL's published 85.3% — eliminating the MAS-vs-single-CoT gap that
ADAS+GEPA would need to navigate. BIRD-dev (released 2023, refreshed
2025-11-06) has dirtier real-world schemas and a strong single-CoT
typically lands 30-45% with current SOTA around 78%.

Submodules:

* :mod:`.dataset` — load BIRD-dev questions + schema extraction.
* :mod:`.baseline` — single-CoT agent (the floor).
* (Re-uses :mod:`orqest.benchmarks.spider.harness` for SQL execution.)
"""

from .dataset import (
    BIRDQuestion,
    extract_schema_ddl,
    load_dev,
    stratified_sample,
)

__all__ = [
    "BIRDQuestion",
    "extract_schema_ddl",
    "load_dev",
    "stratified_sample",
]
