"""Tests for orqest.autonomy.topology_orchestrator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.autonomy.topology_orchestrator import (
    TopologyExecutionResult,
    TopologyOrchestrator,
)
from orqest.observability.events import EventBus
from orqest.optimization.meta_agent import TopologyDesign
from orqest.autonomy.runtime import (
    InMemoryLRU,
    RuntimeTopologyDesigner,
)
from orqest.orchestration.hydrate import CallableRegistry
from orqest.orchestration.spec import (
    AgentStepSpec,
    ParallelSpec,
    PipelineSpec,
    PipelineStepEntry,
    RefinementLoopSpec,
)


class _Out(BaseModel):
    answer: str


class _StubAgent(BaseAgent[GlobalState, _Out]):
    async def _run_implementation(self, state: GlobalState, **kwargs: Any) -> _Out:
        latest = state.get_latest_message("user") or ""
        result = await self.call_model(latest, state)
        return result.output


def _make_factory(label: str):
    def _f() -> _StubAgent:
        return _StubAgent(
            agent_name=label,
            system_prompt=f"you are {label}",
            output_type=_Out,
            model=TestModel(custom_output_args={"answer": f"{label}-out"}),
        )

    return _f


@pytest.fixture
def agent_registry():
    return {
        "cot": _make_factory("cot"),
        "verifier": _make_factory("verifier"),
    }


@pytest.fixture
def callable_registry():
    return CallableRegistry()


@pytest.fixture
def cot_pipeline():
    return PipelineSpec(
        steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="cot"))]
    )


def _designer(
    callable_registry,
    agent_registry,
    designs: list[TopologyDesign],
    *,
    cache=None,
):
    fake = MagicMock(spec=BaseAgent)
    fake.run = AsyncMock(
        side_effect=[MagicMock(output=d) for d in designs]
    )
    return RuntimeTopologyDesigner(
        designer_agent=fake,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
        cache=cache,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_success_result(
    callable_registry, agent_registry, cot_pipeline
):
    designer = _designer(
        callable_registry,
        agent_registry,
        [TopologyDesign(thought="t", spec=cot_pipeline)],
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    result = await orchestrator.execute("hi")
    assert isinstance(result, TopologyExecutionResult)
    assert result.success is True
    assert result.spec_kind == "pipeline"
    assert result.n_agents == 1
    assert result.depth == 1
    assert result.error is None


# ---------------------------------------------------------------------------
# Cache hit short-circuits designer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_short_circuits(
    callable_registry, agent_registry, cot_pipeline
):
    cache = InMemoryLRU()
    await cache.store("hi", cot_pipeline)

    fake = MagicMock(spec=BaseAgent)
    fake.run = AsyncMock(side_effect=[])
    designer = RuntimeTopologyDesigner(
        designer_agent=fake,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
        cache=cache,
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    result = await orchestrator.execute("hi")
    assert result.success is True
    assert result.cache_hit is True
    assert fake.run.await_count == 0


# ---------------------------------------------------------------------------
# Failure path: execution exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_exception_recorded_and_reraised(
    callable_registry, agent_registry, cot_pipeline
):
    """When the hydrated topology raises during run, cache.store(success=False)
    fires and the exception propagates."""
    cache = InMemoryLRU()
    await cache.store("hi", cot_pipeline)
    fake = MagicMock(spec=BaseAgent)
    fake.run = AsyncMock(side_effect=[])
    designer = RuntimeTopologyDesigner(
        designer_agent=fake,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
        cache=cache,
    )

    # Force topology.run to raise by removing the agent from the registry
    # AFTER caching, but verify_on_hit will catch it. Disable verify_on_hit
    # so we get all the way to topology.run.
    designer._verify_on_hit = False
    bad_orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry={},  # empty — will fail at topology_from_spec
    )
    with pytest.raises(Exception):  # noqa: B017, BLE001
        await bad_orchestrator.execute("hi")
    # Cache should have decayed (LRU evicts on success=False)
    assert await cache.lookup("hi") is None


# ---------------------------------------------------------------------------
# Bus event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_emits_execution_completed(
    callable_registry, agent_registry, cot_pipeline
):
    bus = EventBus()
    received: list[Any] = []
    bus.subscribe("topology.execution_completed", received.append)

    designer = _designer(
        callable_registry,
        agent_registry,
        [TopologyDesign(thought="t", spec=cot_pipeline)],
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
        bus=bus,
    )
    await orchestrator.execute("goal")

    import asyncio
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].data["success"] is True
    assert received[0].data["spec_kind"] == "pipeline"


# ---------------------------------------------------------------------------
# Unpacking — Parallel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpacks_parallel_result_merged(
    callable_registry, agent_registry
):
    par = ParallelSpec(
        steps=[AgentStepSpec(agent_name="cot")], merge="first_wins"
    )
    designer = _designer(
        callable_registry,
        agent_registry,
        [TopologyDesign(thought="t", spec=par)],
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    result = await orchestrator.execute("hi")
    assert result.success is True
    # first_wins surfaces the cot agent's output (an _Out instance)
    assert isinstance(result.output, _Out)


# ---------------------------------------------------------------------------
# n_agents / depth recorded correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structural_metrics_populated(
    callable_registry, agent_registry
):
    spec = PipelineSpec(
        steps=[
            PipelineStepEntry(operation=AgentStepSpec(agent_name="cot")),
            PipelineStepEntry(operation=AgentStepSpec(agent_name="verifier")),
        ]
    )
    designer = _designer(
        callable_registry,
        agent_registry,
        [TopologyDesign(thought="t", spec=spec)],
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    result = await orchestrator.execute("hi")
    assert result.n_agents == 2
    assert result.depth == 1


# ---------------------------------------------------------------------------
# design_ms ~0 on cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_design_ms_low_on_cache_hit(
    callable_registry, agent_registry, cot_pipeline
):
    cache = InMemoryLRU()
    await cache.store("hi", cot_pipeline)
    fake = MagicMock(spec=BaseAgent)
    fake.run = AsyncMock()
    designer = RuntimeTopologyDesigner(
        designer_agent=fake,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
        cache=cache,
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    result = await orchestrator.execute("hi")
    # Cache lookup is fast — should be well under 100ms
    assert result.design_ms < 100.0
    assert result.cache_hit is True


# ---------------------------------------------------------------------------
# Context propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_dict_propagates_to_designer(
    callable_registry, agent_registry, cot_pipeline
):
    captured: dict[str, Any] = {}

    fake = MagicMock(spec=BaseAgent)

    async def capture_run(state):
        captured["prompt"] = state.get_latest_message("user")
        return MagicMock(output=TopologyDesign(thought="t", spec=cot_pipeline))

    fake.run = AsyncMock(side_effect=capture_run)
    designer = RuntimeTopologyDesigner(
        designer_agent=fake,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    await orchestrator.execute("hi", context={"caller_id": "test_user_42"})
    # Context dict serialized into prompt
    assert "test_user_42" in captured["prompt"]


# ---------------------------------------------------------------------------
# designer property
# ---------------------------------------------------------------------------


def test_designer_property_returns_wrapped(
    callable_registry, agent_registry, cot_pipeline
):
    designer = _designer(
        callable_registry,
        agent_registry,
        [TopologyDesign(thought="t", spec=cot_pipeline)],
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    assert orchestrator.designer is designer


# ---------------------------------------------------------------------------
# RefinementLoop unpacking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpacks_refinement_loop_output(
    callable_registry, agent_registry
):
    """A RefinementLoop with a passing evaluator should yield LoopResult.output."""

    def _passing_evaluator(_output):
        from orqest.orchestration.loop import EvalResult
        return EvalResult(passed=True, score=1.0)

    callable_registry.register("always_pass", _passing_evaluator)
    callable_registry.register("noop", lambda inp, out, ev: inp)

    spec = RefinementLoopSpec(
        step=AgentStepSpec(agent_name="cot"),
        evaluator="always_pass",
        state_updater_name="noop",
        max_iterations=2,
    )
    designer = _designer(
        callable_registry,
        agent_registry,
        [TopologyDesign(thought="t", spec=spec)],
    )
    orchestrator = TopologyOrchestrator(
        designer,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
    )
    result = await orchestrator.execute("hi")
    assert result.success is True
    assert isinstance(result.output, _Out)
    assert result.spec_kind == "refinement_loop"
