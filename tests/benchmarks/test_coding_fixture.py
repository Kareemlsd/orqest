"""Data-integrity check for the coding benchmark fixture.

This test exists for one reason: catch silent data loss / corruption if
someone edits `benchmarks/coding/codebench.py`. We pin the expected counts
(10 problems, 92 hidden tests) and verify the score harness produces sane
values on a trivially-correct candidate. No LLM calls; runs in <1s.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CODEBENCH_PATH = Path(__file__).resolve().parents[2] / "benchmarks" / "coding" / "codebench.py"


def _load_codebench():
    """Load codebench.py without depending on it being on sys.path."""
    spec = importlib.util.spec_from_file_location("_codebench_under_test", _CODEBENCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_codebench_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_fixture_loads_with_expected_counts():
    cb = _load_codebench()
    assert len(cb.PROBLEMS) == 10, "benchmark must ship exactly 10 problems"
    total_tests = sum(len(p.tests) for p in cb.PROBLEMS)
    assert total_tests == 92, (
        f"benchmark hidden-test count drifted to {total_tests}; pin is 92"
    )


def test_every_problem_has_at_least_5_tests():
    cb = _load_codebench()
    for p in cb.PROBLEMS:
        assert len(p.tests) >= 5, f"problem {p.name!r} has only {len(p.tests)} tests"


def test_score_candidate_runs_on_trivial_solution():
    """Smoke check: scoring a deliberately-wrong stub returns a 0-pass result
    without raising. Catches breakage in the harness if codebench drifts."""
    cb = _load_codebench()
    p0 = cb.PROBLEMS[0]  # parse_roman
    stub = "def parse_roman(s):\n    return None"
    result = cb.score_candidate(stub, p0)
    assert result["problem"] == p0.name
    assert result["total"] == len(p0.tests)
    # `parse_roman('')` and other "must return None" tests pass — but
    # value tests like `parse_roman('III') == 3` fail. So 0 < passed < total.
    assert 0 <= result["passed"] < result["total"]


def test_aggregate_handles_empty_input():
    cb = _load_codebench()
    agg = cb.aggregate([])
    assert agg["pass_at_1"] == 0.0
    assert agg["test_pass_rate"] == 0.0
    assert agg["n_problems"] == 0
