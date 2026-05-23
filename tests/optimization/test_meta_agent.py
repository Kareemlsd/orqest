"""Tests for orqest.optimization.meta_agent — Archive + MetaAgentSearch loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.observability.events import EventBus
from orqest.optimization.bundle import MetricBundle, MetricWeights
from orqest.optimization.evaluator import GoldExample
from orqest.optimization.meta_agent import (
    Archive,
    ArchiveEntry,
    MetaAgentConfig,
    MetaAgentSearch,
    TopologyDesign,
    _aggregate,
    _find_parent_idx,
)
from orqest.optimization.runner import OptimizationResult
from orqest.optimization.topology import TopologyEvaluator, TopologyGene
from orqest.orchestration.hydrate import CallableRegistry
from orqest.orchestration.spec import (
    AgentStepSpec,
    ParallelSpec,
    PipelineSpec,
    PipelineStepEntry,
)


# --- Fixtures ----------------------------------------------------------------


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
def seed_pipeline():
    return PipelineSpec(
        steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="cot"))]
    )


@pytest.fixture
def alt_pipeline():
    return PipelineSpec(
        steps=[
            PipelineStepEntry(operation=AgentStepSpec(agent_name="cot")),
            PipelineStepEntry(operation=AgentStepSpec(agent_name="verifier")),
        ]
    )


@pytest.fixture
def gene(seed_pipeline):
    return TopologyGene(name="main", initial=seed_pipeline)


@pytest.fixture
def evaluator():
    """A TopologyEvaluator that always scores 1.0 — keeps tests deterministic."""
    return TopologyEvaluator(
        score_fn=lambda o, e: 1.0 if "cot" in str(o) else 0.5,
        callable_registry=CallableRegistry(),
        agent_registry={"cot": _make_factory("cot"), "verifier": _make_factory("verifier")},
    )


def _make_search(
    gene: TopologyGene,
    evaluator: TopologyEvaluator,
    *,
    config: MetaAgentConfig | None = None,
    bus: EventBus | None = None,
) -> MetaAgentSearch:
    return MetaAgentSearch(
        config or MetaAgentConfig(n_generations=2, debug_max=1, reflexion_passes=0),
        gene=gene,
        evaluator=evaluator,
        meta_agent_model="openai:gpt-4.1",
        api_key="sk-fake",
        bus=bus,
    )


def _patch_meta_agent(
    search: MetaAgentSearch, *, designs: list[TopologyDesign]
) -> AsyncMock:
    """Patch search._meta_agent.run to yield the given designs sequentially.

    Each yield wraps the design in a MagicMock with a .output attribute, since
    pydantic-ai's AgentRunResult exposes output that way.
    """
    fake = AsyncMock()

    def _make_result(d):
        m = MagicMock()
        m.output = d
        return m

    fake.side_effect = [_make_result(d) for d in designs]
    search._meta_agent.run = fake  # type: ignore[method-assign]
    return fake


# --- MetaAgentConfig --------------------------------------------------------


class TestMetaAgentConfig:
    def test_defaults(self):
        cfg = MetaAgentConfig()
        assert cfg.n_generations == 10
        assert cfg.archive_strategy == "top_k"
        assert cfg.archive_size == 5
        assert cfg.reflexion_passes == 2
        assert cfg.debug_max == 3

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"n_generations": 0},
            {"archive_size": 0},
            {"reflexion_passes": -1},
            {"debug_max": -1},
            {"minibatch_size": 0},
            {"archive_strategy": "ghost"},
        ],
    )
    def test_validation_rejects(self, kwargs):
        with pytest.raises(ValueError):
            MetaAgentConfig(**kwargs)


# --- Archive ----------------------------------------------------------------


def _entry(score: float, gen: int = 0, *, accuracy: float | None = None, cost: float = 0.0, lat: float = 0.0) -> ArchiveEntry:
    return ArchiveEntry(
        generation=gen,
        spec_json="{}",
        bundles=[
            MetricBundle(
                accuracy=accuracy if accuracy is not None else score,
                cost_usd=cost,
                latency_ms=lat,
            )
        ],
        aggregate_score=score,
        thought=f"gen-{gen}",
    )


class TestArchive:
    def test_add_and_best(self):
        a = Archive()
        a.add(_entry(0.5))
        a.add(_entry(0.8))
        a.add(_entry(0.3))
        assert a.best().aggregate_score == 0.8

    def test_top_k_serialization_picks_top_n(self):
        a = Archive(strategy="top_k", size=2)
        for s in [0.1, 0.9, 0.5, 0.7]:
            a.add(_entry(s))
        s = a.serialize_for_prompt()
        # Top 2 by score: 0.9, 0.7
        assert "0.9" in s and "0.7" in s
        assert "0.1" not in s
        assert "0.5" not in s

    def test_cumulative_includes_all(self):
        a = Archive(strategy="cumulative", size=2)
        for s in [0.1, 0.9, 0.5]:
            a.add(_entry(s))
        s = a.serialize_for_prompt()
        for v in [0.1, 0.9, 0.5]:
            assert str(v) in s

    def test_parallel_emits_empty(self):
        a = Archive(strategy="parallel", size=5)
        a.add(_entry(0.5))
        assert a.serialize_for_prompt() == ""

    def test_pareto_returns_non_dominated(self):
        a = Archive()
        # entry A: high acc, low cost — should be on front
        a.add(_entry(0.8, gen=0, accuracy=0.9, cost=0.01, lat=100.0))
        # entry B: dominated by A on every axis
        a.add(_entry(0.5, gen=1, accuracy=0.6, cost=0.05, lat=200.0))
        # entry C: low acc, very low cost — also on front (different tradeoff)
        a.add(_entry(0.4, gen=2, accuracy=0.5, cost=0.001, lat=50.0))
        front = a.pareto()
        assert len(front) == 2  # A and C; B is dominated

    def test_empty_archive_best_raises(self):
        with pytest.raises(ValueError):
            Archive().best()

    def test_pareto_empty_returns_empty(self):
        assert Archive().pareto() == []


# --- _aggregate / _find_parent_idx ------------------------------------------


def test_aggregate_mean():
    bundles = [MetricBundle(accuracy=0.5), MetricBundle(accuracy=1.0)]
    avg = _aggregate(bundles, MetricWeights(accuracy=1.0, confidence=0, cost_usd=0, latency_ms=0, robustness=0))
    assert avg == pytest.approx(0.75)


def test_aggregate_empty_zero():
    assert _aggregate([], MetricWeights()) == 0.0


def test_find_parent_idx_picks_best():
    a = Archive()
    a.add(_entry(0.3))
    a.add(_entry(0.9))
    a.add(_entry(0.5))
    assert _find_parent_idx(a) == 1


# --- MetaAgentSearch end-to-end (mocked LLM) --------------------------------


@pytest.mark.asyncio
async def test_search_seed_and_generations_evaluated(gene, evaluator, alt_pipeline):
    """Full mocked-LLM happy path: seed + 2 designed generations."""
    search = _make_search(
        gene, evaluator,
        config=MetaAgentConfig(n_generations=2, reflexion_passes=0, debug_max=1),
    )
    designs = [
        TopologyDesign(thought="first design", spec=alt_pipeline),
        TopologyDesign(thought="second design", spec=alt_pipeline),
    ]
    fake = _patch_meta_agent(search, designs=designs)

    examples = [GoldExample[str, _Out](input=f"q{i}") for i in range(3)]
    result = await search.run(trainset=examples)

    assert isinstance(result, OptimizationResult)
    # Seed + 2 designed = 3 entries in archive
    assert len(result.raw.entries) == 3
    # Both designs were emitted (2 calls to fake)
    assert fake.await_count == 2
    # History records seed + 2 generations
    assert len(result.history) == 3
    assert result.history[0]["generation"] == -1


@pytest.mark.asyncio
async def test_search_reflexion_passes_invoke_extra_calls(gene, evaluator, alt_pipeline):
    """With reflexion_passes=2 each generation makes 1 design + 2 reflexion calls."""
    search = _make_search(
        gene, evaluator,
        config=MetaAgentConfig(n_generations=1, reflexion_passes=2, debug_max=0),
    )
    designs = [
        TopologyDesign(thought="design", spec=alt_pipeline),
        TopologyDesign(thought="reflex 1", spec=alt_pipeline),
        TopologyDesign(thought="reflex 2", spec=alt_pipeline),
    ]
    fake = _patch_meta_agent(search, designs=designs)

    await search.run(trainset=[GoldExample[str, _Out](input="q")])
    # 3 calls total: 1 design + 2 reflexion
    assert fake.await_count == 3


@pytest.mark.asyncio
async def test_search_debug_retry_on_evaluator_error(gene, alt_pipeline):
    """A topology that fails hydration triggers debug-retry with corrected design."""
    # Evaluator with empty agent registry — first design fails, retry with valid one.
    bad_agent = AgentStepSpec(agent_name="ghost")
    bad_pipeline = PipelineSpec(steps=[PipelineStepEntry(operation=bad_agent)])
    good_pipeline = alt_pipeline

    evaluator = TopologyEvaluator(
        score_fn=lambda o, e: 1.0,
        callable_registry=CallableRegistry(),
        agent_registry={"cot": _make_factory("cot"), "verifier": _make_factory("verifier")},
    )
    search = _make_search(
        gene, evaluator,
        config=MetaAgentConfig(n_generations=1, reflexion_passes=0, debug_max=2),
    )
    designs = [
        TopologyDesign(thought="bad", spec=bad_pipeline),  # design step
        TopologyDesign(thought="good", spec=good_pipeline),  # debug retry
    ]
    fake = _patch_meta_agent(search, designs=designs)

    result = await search.run(trainset=[GoldExample[str, _Out](input="q")])
    # 2 calls: design + debug retry
    assert fake.await_count == 2
    # Result has seed + 1 successful generation
    assert len(result.raw.entries) == 2


@pytest.mark.asyncio
async def test_search_skips_when_debug_max_exhausted(gene, alt_pipeline):
    """When debug_max retries can't fix the topology, the generation is skipped."""
    bad_pipeline = PipelineSpec(
        steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="ghost"))]
    )
    evaluator = TopologyEvaluator(
        score_fn=lambda o, e: 1.0,
        callable_registry=CallableRegistry(),
        agent_registry={"cot": _make_factory("cot")},  # no 'ghost'
    )
    search = _make_search(
        gene, evaluator,
        config=MetaAgentConfig(n_generations=1, reflexion_passes=0, debug_max=2),
    )
    # Every design is bad
    designs = [TopologyDesign(thought=f"bad{i}", spec=bad_pipeline) for i in range(4)]
    _patch_meta_agent(search, designs=designs)

    result = await search.run(trainset=[GoldExample[str, _Out](input="q")])
    # Seed only; the generation was skipped after exhausting retries
    assert len(result.raw.entries) == 1
    # History records the skip
    skipped = [h for h in result.history if h.get("skipped")]
    assert len(skipped) == 1
    assert "debug_max_exhausted" in skipped[0]["reason"]


@pytest.mark.asyncio
async def test_search_emits_iteration_events_when_bus_set(gene, evaluator, alt_pipeline):
    """Bus receives meta_agent.iteration_completed for seed + each generation."""
    bus = EventBus()
    received: list[Any] = []
    bus.subscribe("meta_agent.iteration_completed", received.append)

    search = _make_search(
        gene, evaluator,
        config=MetaAgentConfig(n_generations=1, reflexion_passes=0, debug_max=1),
        bus=bus,
    )
    _patch_meta_agent(
        search, designs=[TopologyDesign(thought="d", spec=alt_pipeline)]
    )
    await search.run(trainset=[GoldExample[str, _Out](input="q")])

    # Allow any background event tasks to flush
    import asyncio

    await asyncio.sleep(0.05)

    assert len(received) >= 2  # seed + 1 generation
    assert received[0].data["phase"] == "seed"


@pytest.mark.asyncio
async def test_search_returns_pareto_candidates(gene, evaluator, alt_pipeline):
    search = _make_search(
        gene, evaluator,
        config=MetaAgentConfig(n_generations=2, reflexion_passes=0, debug_max=1),
    )
    _patch_meta_agent(
        search,
        designs=[
            TopologyDesign(thought="d1", spec=alt_pipeline),
            TopologyDesign(thought="d2", spec=ParallelSpec(steps=[AgentStepSpec(agent_name="cot")])),
        ],
    )
    result = await search.run(trainset=[GoldExample[str, _Out](input="q")])
    assert len(result.pareto_candidates) >= 1
    # Each pareto candidate is shaped like best_candidate (gene_name → spec_json)
    for cand in result.pareto_candidates:
        assert "main" in cand


@pytest.mark.asyncio
async def test_search_empty_trainset_raises(gene, evaluator):
    search = _make_search(gene, evaluator)
    with pytest.raises(ValueError, match="trainset"):
        await search.run(trainset=[])


@pytest.mark.asyncio
async def test_search_design_step_failure_records_in_history(gene, evaluator):
    """When the meta agent itself raises (network/parse failure), generation skips."""
    search = _make_search(
        gene, evaluator,
        config=MetaAgentConfig(n_generations=1, reflexion_passes=0, debug_max=0),
    )
    # First call (seed evaluation doesn't use meta agent), second call (design step) raises
    fake = AsyncMock(side_effect=RuntimeError("network down"))
    search._meta_agent.run = fake  # type: ignore[method-assign]

    result = await search.run(trainset=[GoldExample[str, _Out](input="q")])
    assert len(result.raw.entries) == 1  # seed only
    skipped = [h for h in result.history if h.get("skipped")]
    assert "design_step_failed" in skipped[0]["reason"]
