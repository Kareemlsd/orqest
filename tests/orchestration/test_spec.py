"""Tests for orqest.orchestration.spec — IR construction and JSON round-trip."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from orqest.autonomy.spec import AgentSpec
from orqest.orchestration.spec import (
    AgentStepSpec,
    FunctionStepSpec,
    OperationSpec,
    ParallelSpec,
    PipelineSpec,
    PipelineStepEntry,
    RefinementLoopSpec,
    RouterSpec,
    RouteSpec,
    StepConfigSpec,
    TopologySpec,
)


def _agent_spec(name: str = "x") -> AgentSpec:
    return AgentSpec(
        name=name,
        system_prompt="hi",
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    )


# --- AgentStepSpec -----------------------------------------------------------


class TestAgentStepSpec:
    def test_agent_name_only(self):
        spec = AgentStepSpec(agent_name="cot")
        assert spec.kind == "agent_step"
        assert spec.agent_name == "cot"
        assert spec.inline_spec is None

    def test_inline_spec_only(self):
        spec = AgentStepSpec(inline_spec=_agent_spec())
        assert spec.agent_name is None
        assert spec.inline_spec is not None

    def test_neither_rejected(self):
        with pytest.raises(ValidationError, match="exactly one of"):
            AgentStepSpec()

    def test_both_rejected(self):
        with pytest.raises(ValidationError, match="exactly one of"):
            AgentStepSpec(agent_name="x", inline_spec=_agent_spec())

    def test_frozen(self):
        spec = AgentStepSpec(agent_name="cot")
        with pytest.raises(ValidationError):
            spec.agent_name = "other"  # type: ignore[misc]


# --- PipelineSpec ------------------------------------------------------------


class TestPipelineSpec:
    def test_min_one_step(self):
        with pytest.raises(ValidationError):
            PipelineSpec(steps=[])

    def test_construction(self):
        spec = PipelineSpec(
            steps=[
                PipelineStepEntry(operation=AgentStepSpec(agent_name="a")),
                PipelineStepEntry(
                    operation=AgentStepSpec(agent_name="b"),
                    config=StepConfigSpec(on_error="skip", max_retries=3),
                ),
            ],
        )
        assert spec.kind == "pipeline"
        assert len(spec.steps) == 2
        assert spec.steps[1].config is not None
        assert spec.steps[1].config.on_error == "skip"

    def test_round_trip_json(self):
        spec = PipelineSpec(
            steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="cot"))]
        )
        restored = PipelineSpec.model_validate_json(spec.model_dump_json())
        assert restored == spec


# --- ParallelSpec / RouterSpec / RefinementLoopSpec basic shape --------------


class TestParallelSpec:
    def test_default_merge(self):
        spec = ParallelSpec(steps=[AgentStepSpec(agent_name="a")])
        assert spec.merge == "collect_all"

    def test_custom_merge_name(self):
        spec = ParallelSpec(steps=[AgentStepSpec(agent_name="a")], merge="my_merge")
        assert spec.merge == "my_merge"


class TestRouterSpec:
    def test_construction(self):
        spec = RouterSpec(
            routes=[
                RouteSpec(name="A", step=AgentStepSpec(agent_name="a"), condition_name="cA"),
            ],
        )
        assert spec.kind == "router"
        assert spec.routes[0].condition_name == "cA"


class TestRefinementLoopSpec:
    def test_construction(self):
        spec = RefinementLoopSpec(
            step=AgentStepSpec(agent_name="x"),
            evaluator="judge",
            state_updater_name="next_input",
            max_iterations=3,
        )
        assert spec.kind == "refinement_loop"
        assert spec.max_iterations == 3


# --- Discriminated-union dispatch -------------------------------------------


class TestDiscriminatedUnion:
    @pytest.mark.parametrize(
        "spec",
        [
            PipelineSpec(steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="a"))]),
            ParallelSpec(steps=[AgentStepSpec(agent_name="a")]),
            RouterSpec(
                routes=[RouteSpec(name="r", step=AgentStepSpec(agent_name="a"), condition_name="c")]
            ),
            RefinementLoopSpec(
                step=AgentStepSpec(agent_name="a"),
                evaluator="judge",
                state_updater_name="up",
            ),
        ],
    )
    def test_topology_spec_round_trip(self, spec):
        ta = TypeAdapter(TopologySpec)
        restored = ta.validate_json(spec.model_dump_json())
        assert restored == spec

    def test_operation_spec_accepts_atomic(self):
        ta = TypeAdapter(OperationSpec)
        atomic = AgentStepSpec(agent_name="x")
        restored = ta.validate_json(atomic.model_dump_json())
        assert restored == atomic

    def test_function_step_atomic(self):
        ta = TypeAdapter(OperationSpec)
        atomic = FunctionStepSpec(callable_name="my_fn")
        restored = ta.validate_json(atomic.model_dump_json())
        assert restored == atomic


# --- Recursion ---------------------------------------------------------------


class TestNestedTopologies:
    def test_router_with_nested_pipeline(self):
        nested_pipe = PipelineSpec(
            steps=[
                PipelineStepEntry(operation=AgentStepSpec(agent_name="cot")),
                PipelineStepEntry(operation=AgentStepSpec(agent_name="verify")),
            ],
        )
        router = RouterSpec(
            routes=[
                RouteSpec(name="complex", step=nested_pipe, condition_name="is_complex"),
                RouteSpec(name="simple", step=AgentStepSpec(agent_name="cot"), condition_name="is_simple"),
            ],
        )
        ta = TypeAdapter(TopologySpec)
        restored = ta.validate_json(router.model_dump_json())
        assert restored == router

    def test_refinement_loop_around_parallel(self):
        loop = RefinementLoopSpec(
            step=ParallelSpec(steps=[AgentStepSpec(agent_name="a"), AgentStepSpec(agent_name="b")]),
            evaluator="judge",
            state_updater_name="up",
        )
        ta = TypeAdapter(TopologySpec)
        restored = ta.validate_json(loop.model_dump_json())
        assert restored == loop

    def test_three_level_nesting(self):
        # Pipeline -> Router -> Pipeline (atomic agents at the leaves)
        leaf = PipelineSpec(steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="leaf"))])
        mid = RouterSpec(routes=[RouteSpec(name="r", step=leaf, condition_name="c")])
        top = PipelineSpec(steps=[PipelineStepEntry(operation=mid)])
        ta = TypeAdapter(TopologySpec)
        restored = ta.validate_json(top.model_dump_json())
        assert restored == top
