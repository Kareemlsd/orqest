"""Tests for orqest.orchestration.hydrate — spec → live runtime objects."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.orchestration.loop import EvalResult, RefinementLoop
from orqest.orchestration.parallel import Parallel, ParallelResult
from orqest.orchestration.pipeline import Pipeline
from orqest.orchestration.router import Router
from orqest.orchestration.spec import (
    AgentStepSpec,
    FunctionStepSpec,
    ParallelSpec,
    PipelineSpec,
    PipelineStepEntry,
    RefinementLoopSpec,
    RouterSpec,
    RouteSpec,
    StepConfigSpec,
)
from orqest.orchestration.hydrate import (
    CallableRegistry,
    _count_agent_steps,
    _topology_depth,
    parallel_from_spec,
    pipeline_from_spec,
    refinement_loop_from_spec,
    router_from_spec,
    topology_from_spec,
)


# --- Fixtures ----------------------------------------------------------------


class _Out(BaseModel):
    answer: str


class _StubAgent(BaseAgent[GlobalState, _Out]):
    async def _run_implementation(self, state: GlobalState, **kwargs: Any) -> _Out:
        latest = state.get_latest_message("user") or ""
        result = await self.call_model(latest, state)
        return result.output


def _make_agent_factory(label: str):
    def _f() -> _StubAgent:
        return _StubAgent(
            agent_name=label,
            system_prompt=f"you are {label}",
            output_type=_Out,
            model=TestModel(custom_output_args={"answer": f"{label}-out"}),
        )

    return _f


@pytest.fixture
def agents():
    return {
        "cot": _make_agent_factory("cot"),
        "verifier": _make_agent_factory("verifier"),
        "judge": _make_agent_factory("judge"),
    }


@pytest.fixture
def callables():
    cr = CallableRegistry()
    cr.register("is_complex", lambda x: len(str(x)) > 5)
    cr.register("is_simple", lambda x: len(str(x)) <= 5)
    cr.register("next_input", lambda inp, out, ev: inp + "_next")

    async def _double(x):
        return x + x

    cr.register("double", _double)
    return cr


# --- CallableRegistry --------------------------------------------------------


class TestCallableRegistry:
    def test_register_and_get(self):
        cr = CallableRegistry()
        cr.register("foo", lambda x: x)
        assert cr.get("foo")(42) == 42

    def test_unknown_name_raises_with_hint(self):
        cr = CallableRegistry()
        cr.register("known", lambda: None)
        with pytest.raises(KeyError, match="known"):
            cr.get("missing")

    def test_names_sorted(self):
        cr = CallableRegistry()
        cr.register("zebra", lambda: None)
        cr.register("apple", lambda: None)
        assert cr.names() == ["apple", "zebra"]

    def test_rejects_non_callable(self):
        cr = CallableRegistry()
        with pytest.raises(TypeError):
            cr.register("nope", "not a function")  # type: ignore[arg-type]

    def test_rejects_empty_name(self):
        cr = CallableRegistry()
        with pytest.raises(ValueError):
            cr.register("", lambda: None)


# --- pipeline_from_spec ------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_from_spec_runs(agents, callables):
    spec = PipelineSpec(
        steps=[
            PipelineStepEntry(operation=AgentStepSpec(agent_name="cot")),
            PipelineStepEntry(operation=AgentStepSpec(agent_name="verifier")),
        ]
    )
    pipeline = pipeline_from_spec(spec, callable_registry=callables, agent_registry=agents)
    assert isinstance(pipeline, Pipeline)
    result = await pipeline.run("hi")
    # Last agent's output wins in a Pipeline
    assert isinstance(result, _Out)
    assert result.answer == "verifier-out"


@pytest.mark.asyncio
async def test_pipeline_with_function_step(agents, callables):
    spec = PipelineSpec(
        steps=[
            PipelineStepEntry(operation=FunctionStepSpec(callable_name="double")),
        ]
    )
    pipeline = pipeline_from_spec(spec, callable_registry=callables, agent_registry=agents)
    result = await pipeline.run("hi")
    assert result == "hihi"


@pytest.mark.asyncio
async def test_pipeline_step_config_translates_error_strategy(agents, callables):
    spec = PipelineSpec(
        steps=[
            PipelineStepEntry(
                operation=AgentStepSpec(agent_name="cot"),
                config=StepConfigSpec(on_error="skip", max_retries=2),
            )
        ]
    )
    pipeline = pipeline_from_spec(spec, callable_registry=callables, agent_registry=agents)
    # We don't exercise the skip path — just verify the StepConfig translated
    # cleanly (no exception at hydration).
    assert isinstance(pipeline, Pipeline)


# --- parallel_from_spec ------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_collect_all(agents, callables):
    spec = ParallelSpec(
        steps=[AgentStepSpec(agent_name="cot"), AgentStepSpec(agent_name="verifier")],
        merge="collect_all",
    )
    parallel = parallel_from_spec(spec, callable_registry=callables, agent_registry=agents)
    assert isinstance(parallel, Parallel)
    result = await parallel.run("hi")
    assert isinstance(result, ParallelResult)
    assert isinstance(result.merged, list)
    assert len(result.merged) == 2


@pytest.mark.asyncio
async def test_parallel_first_wins(agents, callables):
    spec = ParallelSpec(
        steps=[AgentStepSpec(agent_name="cot"), AgentStepSpec(agent_name="verifier")],
        merge="first_wins",
    )
    parallel = parallel_from_spec(spec, callable_registry=callables, agent_registry=agents)
    result = await parallel.run("hi")
    assert result.merged is not None  # one of the two outputs


@pytest.mark.asyncio
async def test_parallel_custom_merge_from_registry(agents, callables):
    callables.register("count_results", lambda outputs: len(outputs))
    spec = ParallelSpec(
        steps=[AgentStepSpec(agent_name="cot"), AgentStepSpec(agent_name="verifier")],
        merge="count_results",
    )
    parallel = parallel_from_spec(spec, callable_registry=callables, agent_registry=agents)
    result = await parallel.run("hi")
    assert result.merged == 2


# --- router_from_spec --------------------------------------------------------


@pytest.mark.asyncio
async def test_router_with_condition(agents, callables):
    spec = RouterSpec(
        routes=[
            RouteSpec(name="complex", step=AgentStepSpec(agent_name="verifier"), condition_name="is_complex"),
            RouteSpec(name="simple", step=AgentStepSpec(agent_name="cot"), condition_name="is_simple"),
        ],
    )
    router = router_from_spec(spec, callable_registry=callables, agent_registry=agents)
    assert isinstance(router, Router)
    long_result = await router.run("hello world")
    assert long_result.answer == "verifier-out"
    short_result = await router.run("hi")
    assert short_result.answer == "cot-out"


@pytest.mark.asyncio
async def test_router_fallback(agents, callables):
    spec = RouterSpec(
        routes=[
            RouteSpec(name="never", step=AgentStepSpec(agent_name="verifier"), condition_name="is_complex"),
        ],
        fallback_step=AgentStepSpec(agent_name="cot"),
    )
    router = router_from_spec(spec, callable_registry=callables, agent_registry=agents)
    result = await router.run("hi")
    assert result.answer == "cot-out"


# --- refinement_loop_from_spec ----------------------------------------------


def _passing_evaluator(_output: Any) -> EvalResult:
    return EvalResult(passed=True, feedback="ok", score=1.0)


@pytest.mark.asyncio
async def test_refinement_loop_with_callable_evaluator(agents, callables):
    callables.register("always_pass", _passing_evaluator)
    spec = RefinementLoopSpec(
        step=AgentStepSpec(agent_name="cot"),
        evaluator="always_pass",
        state_updater_name="next_input",
        max_iterations=3,
    )
    loop = refinement_loop_from_spec(spec, callable_registry=callables, agent_registry=agents)
    assert isinstance(loop, RefinementLoop)
    result = await loop.run("hi")
    # passing evaluator → exits on iteration 1
    assert result.iterations == 1
    assert result.exit_reason == "passed"


# --- topology_from_spec dispatch --------------------------------------------


@pytest.mark.asyncio
async def test_topology_dispatch_pipeline(agents, callables):
    spec = PipelineSpec(steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="cot"))])
    obj = topology_from_spec(spec, callable_registry=callables, agent_registry=agents)
    assert isinstance(obj, Pipeline)


@pytest.mark.asyncio
async def test_topology_dispatch_router(agents, callables):
    spec = RouterSpec(
        routes=[RouteSpec(name="r", step=AgentStepSpec(agent_name="cot"), condition_name="is_simple")],
    )
    obj = topology_from_spec(spec, callable_registry=callables, agent_registry=agents)
    assert isinstance(obj, Router)


# --- Nested topology end-to-end ---------------------------------------------


@pytest.mark.asyncio
async def test_nested_router_with_pipeline_inside_route(agents, callables):
    """A Router whose 'complex' route runs a 2-step Pipeline."""
    pipe = PipelineSpec(
        steps=[
            PipelineStepEntry(operation=AgentStepSpec(agent_name="cot")),
            PipelineStepEntry(operation=AgentStepSpec(agent_name="verifier")),
        ]
    )
    spec = RouterSpec(
        routes=[
            RouteSpec(name="complex", step=pipe, condition_name="is_complex"),
        ],
        fallback_step=AgentStepSpec(agent_name="cot"),
    )
    router = topology_from_spec(spec, callable_registry=callables, agent_registry=agents)
    long_result = await router.run("hello world")
    # Pipeline ran → final step is verifier
    assert long_result.answer == "verifier-out"
    short_result = await router.run("hi")
    # fallback ran → cot
    assert short_result.answer == "cot-out"


# --- Error paths -------------------------------------------------------------


def test_unknown_callable_raises_keyerror_with_hint(agents, callables):
    spec = PipelineSpec(steps=[PipelineStepEntry(operation=FunctionStepSpec(callable_name="unknown"))])
    with pytest.raises(KeyError, match="unknown"):
        pipeline_from_spec(spec, callable_registry=callables, agent_registry=agents)


def test_unknown_agent_name_raises_keyerror_with_hint(callables):
    spec = PipelineSpec(steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="ghost"))])
    with pytest.raises(KeyError, match="ghost"):
        pipeline_from_spec(spec, callable_registry=callables, agent_registry={})


def test_inline_spec_without_factory_raises():
    from orqest.autonomy.spec import AgentSpec

    spec = PipelineSpec(
        steps=[
            PipelineStepEntry(
                operation=AgentStepSpec(
                    inline_spec=AgentSpec(name="x", system_prompt="", output_schema={}),
                )
            )
        ]
    )
    with pytest.raises(ValueError, match="AgentFactory"):
        pipeline_from_spec(spec, callable_registry=CallableRegistry(), agent_registry={})


# --- Structural metrics (used by TopologyEvaluator later) -------------------


class TestStructuralMetrics:
    def test_n_agents_simple(self):
        spec = AgentStepSpec(agent_name="x")
        assert _count_agent_steps(spec) == 1

    def test_n_agents_pipeline(self):
        spec = PipelineSpec(
            steps=[
                PipelineStepEntry(operation=AgentStepSpec(agent_name="a")),
                PipelineStepEntry(operation=AgentStepSpec(agent_name="b")),
                PipelineStepEntry(operation=FunctionStepSpec(callable_name="fn")),
            ]
        )
        # 2 agents (FunctionStep doesn't count)
        assert _count_agent_steps(spec) == 2

    def test_depth_pipeline_of_pipelines(self):
        leaf = PipelineSpec(steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="leaf"))])
        mid = PipelineSpec(steps=[PipelineStepEntry(operation=leaf)])
        top = PipelineSpec(steps=[PipelineStepEntry(operation=mid)])
        assert _topology_depth(top) == 3
