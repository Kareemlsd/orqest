"""Benchmarks for validating Orqest's distinctive capabilities.

Each submodule is a self-contained validation target — dataset loader,
evaluation harness, baseline agent, and results persistence. The
intent is that an ADAS + GEPA run can be pointed at any benchmark
and produce a comparable :class:`orqest.optimization.runner.OptimizationResult`.

Current benchmarks:

* :mod:`orqest.benchmarks.spider` — Text-to-SQL on the Spider 1.0 dev split
  (1034 questions, 20 SQLite DBs, mechanical execution-accuracy eval).

Planned (post-v1):

* SciFact / Qasper — scientific claim verification with citation grounding.
* HumanEval+ / MBPP+ — code generation with unit tests.
"""
