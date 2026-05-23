"""Tests for orqest.autonomy.runtime — caches + RuntimeTopologyDesigner."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.memory.local import LocalMemoryStore
from orqest.memory.store import MemoryEntry, MemoryFilter
from orqest.observability.events import EventBus
from orqest.optimization.meta_agent import TopologyDesign
from orqest.autonomy.runtime import (
    InMemoryLRU,
    MemoryStoreCache,
    NoCache,
    RuntimeTopologyDesigner,
    TopologyCache,
)
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
def agent_registry():
    return {
        "cot": _make_factory("cot"),
        "verifier": _make_factory("verifier"),
    }


@pytest.fixture
def callable_registry():
    return CallableRegistry()


def _designer_agent_returning(designs: list[TopologyDesign]) -> Any:
    """Build a fake designer_agent whose .run() yields these designs sequentially."""
    fake = MagicMock(spec=BaseAgent)
    fake.run = AsyncMock(
        side_effect=[
            MagicMock(output=d) if not isinstance(d, Exception) else d
            for d in designs
        ]
    )
    return fake


# ---------------------------------------------------------------------------
# NoCache
# ---------------------------------------------------------------------------


class TestNoCache:
    @pytest.mark.asyncio
    async def test_lookup_always_none(self, seed_pipeline):
        nc = NoCache()
        assert await nc.lookup("any goal") is None

    @pytest.mark.asyncio
    async def test_store_no_op(self, seed_pipeline):
        nc = NoCache()
        await nc.store("g", seed_pipeline, success=True)
        await nc.store("g", seed_pipeline, success=False)
        assert await nc.lookup("g") is None

    def test_satisfies_protocol(self):
        assert isinstance(NoCache(), TopologyCache)


# ---------------------------------------------------------------------------
# InMemoryLRU
# ---------------------------------------------------------------------------


class TestInMemoryLRU:
    def test_satisfies_protocol(self):
        assert isinstance(InMemoryLRU(), TopologyCache)

    def test_max_size_validated(self):
        with pytest.raises(ValueError):
            InMemoryLRU(max_size=0)

    @pytest.mark.asyncio
    async def test_exact_match_hit(self, seed_pipeline):
        lru = InMemoryLRU()
        await lru.store("g", seed_pipeline)
        assert await lru.lookup("g") == seed_pipeline

    @pytest.mark.asyncio
    async def test_miss_returns_none(self, seed_pipeline):
        lru = InMemoryLRU()
        await lru.store("g", seed_pipeline)
        assert await lru.lookup("other") is None

    @pytest.mark.asyncio
    async def test_eviction_at_max_size(self, seed_pipeline):
        lru = InMemoryLRU(max_size=2)
        await lru.store("a", seed_pipeline)
        await lru.store("b", seed_pipeline)
        await lru.store("c", seed_pipeline)
        # 'a' is the oldest, should be evicted
        assert await lru.lookup("a") is None
        assert await lru.lookup("b") == seed_pipeline
        assert await lru.lookup("c") == seed_pipeline

    @pytest.mark.asyncio
    async def test_failure_evicts(self, seed_pipeline):
        lru = InMemoryLRU()
        await lru.store("g", seed_pipeline)
        await lru.store("g", seed_pipeline, success=False)
        assert await lru.lookup("g") is None


# ---------------------------------------------------------------------------
# MemoryStoreCache
# ---------------------------------------------------------------------------


class TestMemoryStoreCache:
    def test_satisfies_protocol(self):
        store = LocalMemoryStore(":memory:")
        assert isinstance(MemoryStoreCache(store), TopologyCache)

    def test_validates_threshold(self):
        store = LocalMemoryStore(":memory:")
        with pytest.raises(ValueError):
            MemoryStoreCache(store, threshold=1.5)

    @pytest.mark.asyncio
    async def test_store_then_lookup_returns_spec(self, seed_pipeline):
        store = LocalMemoryStore(":memory:")
        cache = MemoryStoreCache(store, threshold=0.0)  # threshold 0 → always match
        await cache.store("test goal", seed_pipeline, success=True)
        recalled = await cache.lookup("test goal")
        assert recalled == seed_pipeline

    @pytest.mark.asyncio
    async def test_miss_returns_none(self):
        store = LocalMemoryStore(":memory:")
        cache = MemoryStoreCache(store)
        assert await cache.lookup("never stored") is None

    @pytest.mark.asyncio
    async def test_namespace_filters_other_semantic_entries(self, seed_pipeline):
        """Real semantic memories with a different source_agent shouldn't surface."""
        store = LocalMemoryStore(":memory:")
        # Insert a regular semantic memory NOT in our namespace
        await store.store(MemoryEntry(
            content="some random fact",
            memory_type="semantic",
            source_agent="other_agent",
        ))
        cache = MemoryStoreCache(store, namespace="topology_cache")
        assert await cache.lookup("some random fact") is None

    @pytest.mark.asyncio
    async def test_failure_decays_reliability(self, seed_pipeline):
        store = LocalMemoryStore(":memory:")
        cache = MemoryStoreCache(store, threshold=0.0, min_reliability=0.0)
        await cache.store("goal", seed_pipeline, success=True)
        # Confirm stored, lookup works
        assert await cache.lookup("goal") == seed_pipeline
        # Trigger failure — should decay
        await cache.store("goal", seed_pipeline, success=False)
        # Bump min_reliability above the decayed value; lookup should now miss
        strict = MemoryStoreCache(store, threshold=0.0, min_reliability=0.9)
        assert await strict.lookup("goal") is None


# ---------------------------------------------------------------------------
# RuntimeTopologyDesigner
# ---------------------------------------------------------------------------


class TestRuntimeTopologyDesigner:
    def test_max_depth_validated(self, callable_registry, agent_registry, seed_pipeline):
        designer_agent = _designer_agent_returning([])
        with pytest.raises(ValueError):
            RuntimeTopologyDesigner(
                designer_agent=designer_agent,
                callable_registry=callable_registry,
                agent_registry=agent_registry,
                max_depth=0,
            )

    @pytest.mark.asyncio
    async def test_cold_design_no_cache_invokes_agent(
        self, callable_registry, agent_registry, alt_pipeline
    ):
        designer_agent = _designer_agent_returning(
            [TopologyDesign(thought="t", spec=alt_pipeline)]
        )
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
        )
        spec = await designer.design("goal")
        assert spec == alt_pipeline
        assert designer_agent.run.await_count == 1
        assert designer.stats.designs == 1
        assert designer.stats.misses == 1

    @pytest.mark.asyncio
    async def test_cache_hit_short_circuits_designer(
        self, callable_registry, agent_registry, seed_pipeline
    ):
        cache = InMemoryLRU()
        await cache.store("goal", seed_pipeline)
        designer_agent = _designer_agent_returning([])
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            cache=cache,
        )
        spec = await designer.design("goal")
        assert spec == seed_pipeline
        assert designer_agent.run.await_count == 0
        assert designer.stats.hits == 1
        assert designer.stats.designs == 0

    @pytest.mark.asyncio
    async def test_verify_on_hit_invalidates_stale(
        self, callable_registry, alt_pipeline
    ):
        """A cached spec referencing a since-removed agent should fall through."""
        cache = InMemoryLRU()
        # Cache a spec that references 'verifier' but the registry won't have it
        await cache.store("goal", alt_pipeline)

        # Empty agent registry — alt_pipeline references 'cot' and 'verifier' which aren't registered
        designer_agent = _designer_agent_returning(
            [TopologyDesign(
                thought="fresh",
                spec=PipelineSpec(steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="only"))])
            )]
        )
        only_registry = {"only": _make_factory("only")}
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=only_registry,
            cache=cache,
            verify_on_hit=True,
        )
        spec = await designer.design("goal")
        # Stale invalidated, fresh design returned
        assert designer.stats.stale_invalidations == 1
        assert designer.stats.designs == 1
        assert designer_agent.run.await_count == 1

    @pytest.mark.asyncio
    async def test_design_failure_no_fallback_raises(
        self, callable_registry, agent_registry
    ):
        """An unhydratable spec from the designer raises when no fallback is set."""
        # Designer emits a spec referencing 'ghost', which is not in agent_registry
        bad_spec = PipelineSpec(
            steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="ghost"))]
        )
        designer_agent = _designer_agent_returning(
            [TopologyDesign(thought="bad", spec=bad_spec)]
        )
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=agent_registry,  # no 'ghost'
        )
        with pytest.raises(RuntimeError, match="runtime topology design failed"):
            await designer.design("goal")
        assert designer.stats.design_failures == 1

    @pytest.mark.asyncio
    async def test_design_failure_returns_fallback(
        self, callable_registry, agent_registry, seed_pipeline
    ):
        bad_spec = PipelineSpec(
            steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="ghost"))]
        )
        designer_agent = _designer_agent_returning(
            [TopologyDesign(thought="bad", spec=bad_spec)]
        )
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            fallback_spec=seed_pipeline,
        )
        spec = await designer.design("goal")
        assert spec == seed_pipeline
        assert designer.stats.fallback_returns == 1

    @pytest.mark.asyncio
    async def test_designer_agent_exception_handled(
        self, callable_registry, agent_registry, seed_pipeline
    ):
        """When the designer agent itself raises, fall back to fallback_spec or RuntimeError."""
        designer_agent = MagicMock(spec=BaseAgent)
        designer_agent.run = AsyncMock(side_effect=RuntimeError("network down"))
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            fallback_spec=seed_pipeline,
        )
        spec = await designer.design("goal")
        assert spec == seed_pipeline

    @pytest.mark.asyncio
    async def test_success_records_to_cache(
        self, callable_registry, agent_registry, alt_pipeline
    ):
        cache = InMemoryLRU()
        designer_agent = _designer_agent_returning(
            [TopologyDesign(thought="t", spec=alt_pipeline)]
        )
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            cache=cache,
        )
        await designer.design("goal")
        # Cache should now have the spec
        assert await cache.lookup("goal") == alt_pipeline

    @pytest.mark.asyncio
    async def test_design_prompt_includes_constraints_and_seed_library(
        self, callable_registry, agent_registry, seed_pipeline, alt_pipeline
    ):
        """The constructed prompt should embed constraints + seed library entries."""
        designer_agent = MagicMock(spec=BaseAgent)
        captured: dict[str, Any] = {}

        async def capture_run(state):
            captured["prompt"] = state.get_latest_message("user")
            return MagicMock(output=TopologyDesign(thought="t", spec=seed_pipeline))

        designer_agent.run = AsyncMock(side_effect=capture_run)
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            constraints="prefer simpler",
            seed_library=[alt_pipeline],
        )
        await designer.design("important goal")
        prompt = captured["prompt"]
        assert "prefer simpler" in prompt
        assert "Library of validated topologies" in prompt
        assert "important goal" in prompt
        assert "cot" in prompt  # agent_registry name surfaced

    @pytest.mark.asyncio
    async def test_emits_bus_events(
        self, callable_registry, agent_registry, alt_pipeline
    ):
        bus = EventBus()
        events: list[Any] = []
        bus.subscribe("topology.designed", events.append)
        bus.subscribe("topology.cache_miss", events.append)

        designer_agent = _designer_agent_returning(
            [TopologyDesign(thought="t", spec=alt_pipeline)]
        )
        designer = RuntimeTopologyDesigner(
            designer_agent=designer_agent,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            bus=bus,
        )
        await designer.design("goal")

        # Allow background event tasks to flush
        import asyncio
        await asyncio.sleep(0.05)

        types = {e.event_type for e in events}
        assert "topology.cache_miss" in types
        assert "topology.designed" in types
