"""Tests for apply_result extending to topology genes (TopologySpec values)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.optimization.apply import apply_result
from orqest.optimization.runner import OptimizationResult
from orqest.optimization.topology import TopologyGene
from orqest.orchestration.spec import (
    AgentStepSpec,
    ParallelSpec,
    PipelineSpec,
    PipelineStepEntry,
)


class _Out(BaseModel):
    answer: str


class _StubAgent(BaseAgent[GlobalState, _Out]):
    async def _run_implementation(self, state: GlobalState, **kwargs: Any) -> _Out:
        latest = state.get_latest_message("user") or ""
        result = await self.call_model(latest, state)
        return result.output


def _make_seed():
    return PipelineSpec(
        steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="cot"))]
    )


def _make_evolved():
    return ParallelSpec(steps=[AgentStepSpec(agent_name="cot")], merge="first_wins")


def _make_result(initial, evolved) -> OptimizationResult:
    return OptimizationResult(
        best_candidate={"main": evolved.model_dump_json()},
        best_decoded={"main": evolved},
        best_score=0.9,
        pareto_candidates=[{"main": evolved.model_dump_json()}],
    )


def test_apply_topology_dry_run_does_not_mutate():
    seed = _make_seed()
    evolved = _make_evolved()
    result = _make_result(seed, evolved)
    target = {"main": seed}
    diffs = apply_result(result, target=target, dry_run=True)
    # Target unchanged
    assert target["main"] == seed
    # Diff still produced
    assert len(diffs) == 1
    assert diffs[0].changed


def test_apply_topology_commit_swaps_in_dict_target():
    seed = _make_seed()
    evolved = _make_evolved()
    result = _make_result(seed, evolved)
    target = {"main": seed}
    apply_result(result, target=target, dry_run=False)
    assert target["main"] == evolved


def test_apply_topology_diff_uses_json_pretty_print():
    seed = _make_seed()
    evolved = _make_evolved()
    result = _make_result(seed, evolved)
    diffs = apply_result(result, target={"main": seed}, dry_run=True)
    # JSON pretty-print = multiline; the unified diff should contain the
    # 'kind' line because both PipelineSpec and ParallelSpec emit "kind":
    assert '"kind"' in diffs[0].unified


def test_apply_topology_no_change_when_seed_equals_evolved():
    seed = _make_seed()
    result = _make_result(seed, seed)
    target = {"main": seed}
    diffs = apply_result(result, target=target, dry_run=False)
    # No mutation needed; diff records before == after
    assert not diffs[0].changed
    assert target["main"] == seed


def test_apply_topology_object_target_setattr():
    """A target object with a 'main' attribute receives the new TopologySpec."""
    seed = _make_seed()
    evolved = _make_evolved()

    class _Holder:
        def __init__(self):
            self.main = seed

    holder = _Holder()
    result = _make_result(seed, evolved)
    apply_result(result, target=holder, dry_run=False)
    assert holder.main == evolved


def test_apply_topology_gene_value_round_trips():
    """The applied value is a TopologySpec (not a JSON string)."""
    seed = _make_seed()
    evolved = _make_evolved()
    target = {"main": seed}
    apply_result(result=_make_result(seed, evolved), target=target, dry_run=False)
    assert isinstance(target["main"], ParallelSpec)
    assert target["main"].merge == "first_wins"
