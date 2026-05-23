"""Tests for apply_result — diff/commit boundary with cache-reset gotcha."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.optimization import (
    OptimizationDiff,
    OptimizationResult,
    apply_result,
)


class _Out(BaseModel):
    answer: str


class _StubAgent(BaseAgent[GlobalState, _Out]):
    async def _run_implementation(
        self, state: GlobalState, **kwargs: Any
    ) -> _Out:
        latest = state.get_latest_message("user") or ""
        result = await self.call_model(latest, state)
        return result.output


def _agent(prompt: str = "Original prompt.") -> _StubAgent:
    return _StubAgent(
        agent_name="stub",
        system_prompt=prompt,
        output_type=_Out,
        model=TestModel(custom_output_args={"answer": "stubbed"}),
    )


def _result(decoded: dict[str, Any]) -> OptimizationResult:
    return OptimizationResult(
        best_candidate={k: str(v) for k, v in decoded.items()},
        best_decoded=decoded,
        best_score=0.9,
        pareto_candidates=[],
    )


def test_dry_run_does_not_mutate_agent():
    agent = _agent("Original.")
    res = _result({"system_prompt": "Evolved prompt."})
    diffs = apply_result(res, target=agent)  # dry_run=True is default
    assert agent.system_prompt == "Original."
    assert len(diffs) == 1
    assert diffs[0].changed
    assert diffs[0].after == "Evolved prompt."


def test_dry_run_returns_diff_objects():
    agent = _agent("Old.")
    res = _result({"system_prompt": "New."})
    diffs = apply_result(res, target=agent, dry_run=True)
    assert isinstance(diffs[0], OptimizationDiff)
    assert "Old" in diffs[0].unified
    assert "New" in diffs[0].unified


def test_commit_mutates_system_prompt():
    agent = _agent("Original.")
    res = _result({"system_prompt": "Evolved."})
    apply_result(res, target=agent, dry_run=False)
    assert agent.system_prompt == "Evolved."


def test_commit_resets_cached_pydantic_ai_agent():
    """The critical regression test. A committed prompt is invisible at
    runtime if the cached pydantic_ai.Agent isn't invalidated.
    """
    agent = _agent("Original.")
    # Force the cache to populate (lazy attribute access via the property)
    _ = agent.agent  # type: ignore[attr-defined] - assumes property exists
    assert agent._agent is not None

    res = _result({"system_prompt": "Evolved."})
    apply_result(res, target=agent, dry_run=False)
    assert agent._agent is None  # Cache invalidated
    assert agent.system_prompt == "Evolved."


def test_no_op_when_before_equals_after():
    agent = _agent("Same.")
    res = _result({"system_prompt": "Same."})
    diffs = apply_result(res, target=agent, dry_run=False)
    assert not diffs[0].changed
    assert diffs[0].unified == ""
    assert agent.system_prompt == "Same."


def test_apply_to_dict_target():
    """A dict target receives the evolved values by key."""
    settings = {"system_prompt": "Original.", "other_key": "untouched"}
    res = _result({"system_prompt": "Evolved."})
    diffs = apply_result(res, target=settings, dry_run=False)
    assert settings["system_prompt"] == "Evolved."
    assert settings["other_key"] == "untouched"
    assert diffs[0].changed
