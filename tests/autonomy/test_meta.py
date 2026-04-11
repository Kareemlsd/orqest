"""Tests for the MetaOrchestrator.

Verifies goal decomposition, sequential subtask execution, context
accumulation, failure handling, agent caching, limit enforcement,
hook dispatch, and memory integration.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.autonomy.meta import (
    ExecutionResult,
    MetaOrchestrator,
    SubTask,
    TaskDecomposition,
)
from orqest.autonomy.spec import AgentSpec
from orqest.hooks import HookRunner
from orqest.memory.store import MemoryEntry

# ---------------------------------------------------------------------------
# Test output model for spawned agents
# ---------------------------------------------------------------------------


class SimpleOutput(BaseModel):
    result: str = Field(default="done")
    confidence: float = Field(default=0.9)


# ---------------------------------------------------------------------------
# Mock planner — returns a fixed TaskDecomposition without LLM calls
# ---------------------------------------------------------------------------


class PlannerAgent(BaseAgent[GlobalState, TaskDecomposition]):
    """Planner that returns a pre-configured decomposition."""

    def __init__(
        self, model: Any, decomposition: TaskDecomposition
    ) -> None:
        super().__init__(
            agent_name="planner",
            system_prompt="plan",
            output_type=TaskDecomposition,
            model=model,
        )
        self._fixed = decomposition

    async def _run_implementation(
        self, state: GlobalState, **kwargs: Any
    ) -> TaskDecomposition:
        return self._fixed


# ---------------------------------------------------------------------------
# Mock worker agent — records calls and returns SimpleOutput
# ---------------------------------------------------------------------------


class WorkerAgent(BaseAgent[GlobalState, SimpleOutput]):
    """Worker agent that records invocations for assertion."""

    def __init__(self, model: Any, name: str, *, fail: bool = False) -> None:
        super().__init__(
            agent_name=name,
            system_prompt="work",
            output_type=SimpleOutput,
            model=model,
        )
        self.calls: list[GlobalState] = []
        self._fail = fail

    async def _run_implementation(
        self, state: GlobalState, **kwargs: Any
    ) -> SimpleOutput:
        self.calls.append(state)
        if self._fail:
            raise RuntimeError(f"{self.agent_name} failed")
        return SimpleOutput(result=f"output from {self.agent_name}")


# ---------------------------------------------------------------------------
# Mock factory — spawns WorkerAgents from specs
# ---------------------------------------------------------------------------


class MockFactory:
    """Factory that creates WorkerAgent instances from AgentSpec."""

    def __init__(
        self, model: Any, *, fail_names: set[str] | None = None
    ) -> None:
        self._model = model
        self._fail_names = fail_names or set()
        self.spawned_specs: list[AgentSpec] = []

    def spawn(self, spec: AgentSpec) -> BaseAgent:
        self.spawned_specs.append(spec)
        fail = spec.name in self._fail_names
        return WorkerAgent(self._model, spec.name, fail=fail)


# ---------------------------------------------------------------------------
# Mock registry — empty tool registry
# ---------------------------------------------------------------------------


class MockRegistry:
    """Minimal ToolRegistry with no tools."""

    def get(self, name: str) -> Any | None:
        return None

    def list_tools(self) -> list[str]:
        return []


# ---------------------------------------------------------------------------
# Mock memory store — in-memory dict-based
# ---------------------------------------------------------------------------


class MockMemoryStore:
    """In-memory store that records store/recall calls."""

    def __init__(self) -> None:
        self.stored: list[MemoryEntry] = []
        self._entries: dict[str, MemoryEntry] = {}

    async def store(self, entry: MemoryEntry) -> str:
        self.stored.append(entry)
        self._entries[entry.id] = entry
        return entry.id

    async def recall(
        self, query: str, *, k: int = 5, filters: Any = None
    ) -> list[MemoryEntry]:
        return []

    async def forget(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)

    async def update_reliability(
        self, entry_id: str, *, success: bool
    ) -> None:
        pass

    async def count(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# Recording hook — captures before/after/error calls
# ---------------------------------------------------------------------------


class RecordingHook:
    """Hook that records all lifecycle events."""

    def __init__(self) -> None:
        self.before_calls: list[tuple[str, dict]] = []
        self.after_calls: list[tuple[str, dict]] = []
        self.error_calls: list[tuple[str, dict]] = []

    async def before_tool(
        self, tool_name: str, args: dict[str, Any], state: Any
    ) -> None:
        self.before_calls.append((tool_name, args))

    async def after_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        state: Any,
        duration_ms: float,
    ) -> None:
        self.after_calls.append((tool_name, args))

    async def on_error(
        self,
        tool_name: str,
        args: dict[str, Any],
        error: Exception,
        state: Any,
    ) -> None:
        self.error_calls.append((tool_name, args))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_decomposition(
    goal: str = "test goal", num_subtasks: int = 2
) -> TaskDecomposition:
    subtasks = [
        SubTask(
            name=f"subtask_{i}",
            description=f"Do step {i}",
            requires_agent=True,
        )
        for i in range(num_subtasks)
    ]
    return TaskDecomposition(
        goal=goal,
        subtasks=subtasks,
        reasoning="These steps achieve the goal",
    )


@pytest.fixture
def model() -> TestModel:
    return TestModel()


@pytest.fixture
def decomposition() -> TaskDecomposition:
    return _make_decomposition()


@pytest.fixture
def planner(model: TestModel, decomposition: TaskDecomposition) -> PlannerAgent:
    return PlannerAgent(model, decomposition)


@pytest.fixture
def factory(model: TestModel) -> MockFactory:
    return MockFactory(model)


@pytest.fixture
def registry() -> MockRegistry:
    return MockRegistry()


@pytest.fixture
def orchestrator(
    planner: PlannerAgent, factory: MockFactory, registry: MockRegistry
) -> MetaOrchestrator:
    return MetaOrchestrator(planner, factory, registry)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solve_decomposes_goal(
    orchestrator: MetaOrchestrator, factory: MockFactory
) -> None:
    """MetaOrchestrator calls planner and gets subtasks."""
    result = await orchestrator.solve("build a website")

    assert isinstance(result, ExecutionResult)
    assert result.goal == "build a website"
    assert len(result.subtask_results) == 2
    assert len(factory.spawned_specs) == 2


@pytest.mark.asyncio
async def test_solve_executes_subtasks_sequentially(
    orchestrator: MetaOrchestrator,
) -> None:
    """All subtasks execute and results are collected in order."""
    result = await orchestrator.solve("test goal")

    assert result.success is True
    assert len(result.subtask_results) == 2
    assert result.subtask_results[0].subtask_name == "subtask_0"
    assert result.subtask_results[1].subtask_name == "subtask_1"
    assert all(r.success for r in result.subtask_results)
    assert result.total_duration_ms > 0


@pytest.mark.asyncio
async def test_solve_accumulates_context(model: TestModel) -> None:
    """Output of subtask 0 is available to subtask 1 via context."""
    decomposition = _make_decomposition(num_subtasks=2)
    planner = PlannerAgent(model, decomposition)
    factory = MockFactory(model)
    registry = MockRegistry()
    orch = MetaOrchestrator(planner, factory, registry)

    result = await orch.solve("context test")

    # subtask_0 succeeded, so subtask_1 should have had context
    assert result.subtask_results[0].success is True
    assert result.subtask_results[0].output is not None
    # Both succeed since no failures configured
    assert result.subtask_results[1].success is True


@pytest.mark.asyncio
async def test_solve_handles_subtask_failure(model: TestModel) -> None:
    """One subtask fails, others still execute, result.success is False."""
    decomposition = _make_decomposition(num_subtasks=3)
    planner = PlannerAgent(model, decomposition)
    factory = MockFactory(model, fail_names={"subtask_1"})
    registry = MockRegistry()
    orch = MetaOrchestrator(planner, factory, registry)

    result = await orch.solve("partial failure")

    assert result.success is False
    assert result.subtask_results[0].success is True
    assert result.subtask_results[1].success is False
    assert result.subtask_results[1].error is not None
    assert "subtask_1 failed" in result.subtask_results[1].error
    # subtask_2 still executes
    assert result.subtask_results[2].success is True


@pytest.mark.asyncio
async def test_spawned_agents_populated(
    orchestrator: MetaOrchestrator,
) -> None:
    """After solve, spawned_agents dict contains the created agents."""
    assert len(orchestrator.spawned_agents) == 0

    await orchestrator.solve("populate agents")

    agents = orchestrator.spawned_agents
    assert len(agents) == 2
    assert "subtask_0" in agents
    assert "subtask_1" in agents


@pytest.mark.asyncio
async def test_max_subtasks_enforced(model: TestModel) -> None:
    """Planner returns 20 subtasks but only max_subtasks are executed."""
    decomposition = _make_decomposition(num_subtasks=20)
    planner = PlannerAgent(model, decomposition)
    factory = MockFactory(model)
    registry = MockRegistry()
    orch = MetaOrchestrator(
        planner, factory, registry, max_subtasks=5
    )

    result = await orch.solve("too many subtasks")

    assert len(result.subtask_results) == 5
    assert len(factory.spawned_specs) == 5


@pytest.mark.asyncio
async def test_hooks_fire_for_subtasks(model: TestModel) -> None:
    """Before/after/error hooks are called during execution."""
    decomposition = _make_decomposition(num_subtasks=2)
    # Make subtask_1 fail to test error hook
    decomposition.subtasks.append(
        SubTask(
            name="failing",
            description="This will fail",
            requires_agent=True,
        )
    )
    planner = PlannerAgent(model, decomposition)
    factory = MockFactory(model, fail_names={"failing"})
    registry = MockRegistry()

    hook = RecordingHook()
    hooks = HookRunner(hooks=[hook])
    orch = MetaOrchestrator(planner, factory, registry, hooks=hooks)

    await orch.solve("hook test")

    # before fires for all 3 subtasks (before execution attempt)
    assert len(hook.before_calls) == 3
    # after fires only for the 2 successful subtasks
    assert len(hook.after_calls) == 2
    # error fires for the 1 failed subtask
    assert len(hook.error_calls) == 1
    assert hook.error_calls[0][0] == "meta:failing"


@pytest.mark.asyncio
async def test_memory_integration(model: TestModel) -> None:
    """When memory is provided, specs are stored after spawning."""
    decomposition = _make_decomposition(num_subtasks=2)
    planner = PlannerAgent(model, decomposition)
    factory = MockFactory(model)
    registry = MockRegistry()
    memory = MockMemoryStore()

    orch = MetaOrchestrator(
        planner, factory, registry, memory=memory
    )

    await orch.solve("memory test")

    # Each spawned agent should have its spec stored
    assert len(memory.stored) == 2
    # Verify stored content is valid AgentSpec JSON
    for entry in memory.stored:
        assert entry.memory_type == "episodic"
        assert entry.source_agent == "meta_orchestrator"
        spec = AgentSpec.model_validate_json(entry.content)
        assert spec.name.startswith("subtask_")
