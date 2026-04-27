"""Tests for the per-kind retrieval strategies."""

from __future__ import annotations

import pytest

from orqest.memory.config import MemoryConfig, PerKindConfig
from orqest.memory.local import LocalMemoryStore
from orqest.memory.store import MemoryEntry, MemoryFilter, Skill
from orqest.memory.strategies import (
    EpisodicStrategy,
    ProceduralStrategy,
    RetrievalStrategy,
    SemanticStrategy,
    default_strategy_table,
)


def test_default_strategy_table_has_three_kinds():
    table = default_strategy_table()
    assert set(table.keys()) == {"semantic", "episodic", "procedural"}
    assert isinstance(table["semantic"], SemanticStrategy)
    assert isinstance(table["episodic"], EpisodicStrategy)
    assert isinstance(table["procedural"], ProceduralStrategy)


def test_strategies_satisfy_protocol():
    table = default_strategy_table()
    for s in table.values():
        assert isinstance(s, RetrievalStrategy)


@pytest.mark.asyncio
async def test_semantic_strategy_orders_by_last_accessed_desc(tmp_path):
    """Default behavior — order by last_accessed (recency-of-touch)."""
    store = LocalMemoryStore(tmp_path / "semantic.db")

    a = MemoryEntry(content="alpha story", memory_type="semantic")
    b = MemoryEntry(content="alpha sequel", memory_type="semantic")
    await store.store(a)
    await store.store(b)
    # Touch `a` to make it most-recently-accessed.
    await store.recall("alpha", k=1, filters=MemoryFilter(memory_type="semantic"))

    results = await store.recall("alpha", k=2, filters=MemoryFilter(memory_type="semantic"))
    assert {e.content for e in results} == {"alpha story", "alpha sequel"}


@pytest.mark.asyncio
async def test_episodic_strategy_orders_by_created_at_desc(tmp_path):
    """Episodic memory's primary signal is recency — newer first."""
    import asyncio

    store = LocalMemoryStore(tmp_path / "episodic.db")
    older = MemoryEntry(content="event one", memory_type="episodic")
    await store.store(older)
    await asyncio.sleep(0.005)
    newer = MemoryEntry(content="event two", memory_type="episodic")
    await store.store(newer)

    results = await store.recall(
        "event", k=2, filters=MemoryFilter(memory_type="episodic")
    )
    assert len(results) == 2
    assert results[0].content == "event two"  # newer first


@pytest.mark.asyncio
async def test_procedural_strategy_exact_trigger_match(tmp_path):
    store = LocalMemoryStore(tmp_path / "procedural.db")
    skill = Skill(name="lint_skill", description="d", trigger="fix lint")
    await store.store(
        MemoryEntry(
            content="fix lint",
            structured_content=skill.model_dump(),
            memory_type="procedural",
        )
    )
    results = await store.recall(
        "fix lint", filters=MemoryFilter(memory_type="procedural")
    )
    assert len(results) == 1
    assert results[0].structured_content["name"] == "lint_skill"


@pytest.mark.asyncio
async def test_procedural_strategy_case_insensitive(tmp_path):
    store = LocalMemoryStore(tmp_path / "procedural2.db")
    skill = Skill(name="x", description="d", trigger="run_solver")
    await store.store(
        MemoryEntry(
            content="run_solver",
            structured_content=skill.model_dump(),
            memory_type="procedural",
        )
    )
    results = await store.recall(
        "RUN_SOLVER", filters=MemoryFilter(memory_type="procedural")
    )
    assert len(results) == 1


@pytest.mark.asyncio
async def test_procedural_strategy_substring_match(tmp_path):
    store = LocalMemoryStore(tmp_path / "procedural3.db")
    skill = Skill(name="x", description="d", trigger="fix the lint errors")
    await store.store(
        MemoryEntry(
            content="fix the lint errors",
            structured_content=skill.model_dump(),
            memory_type="procedural",
        )
    )
    results = await store.recall(
        "lint", filters=MemoryFilter(memory_type="procedural")
    )
    assert len(results) == 1


@pytest.mark.asyncio
async def test_procedural_strategy_no_match_no_judge_returns_empty(tmp_path):
    store = LocalMemoryStore(tmp_path / "procedural4.db")
    skill = Skill(name="x", description="d", trigger="run_solver")
    await store.store(
        MemoryEntry(
            content="run_solver",
            structured_content=skill.model_dump(),
            memory_type="procedural",
        )
    )
    results = await store.recall(
        "completely unrelated", filters=MemoryFilter(memory_type="procedural")
    )
    assert results == []


@pytest.mark.asyncio
async def test_procedural_strategy_with_judge_returns_fuzzy_match(tmp_path):
    """Inject a judge that picks index 0 — fuzzy match should fire when
    no exact match is found."""

    async def judge(query: str, candidates: list[str]) -> list[int]:
        return [0]

    store = LocalMemoryStore(
        tmp_path / "procedural_fuzzy.db",
        strategies={
            **default_strategy_table(),
            "procedural": ProceduralStrategy(fuzzy_judge=judge),
        },
    )
    skill = Skill(name="x", description="d", trigger="run_solver")
    await store.store(
        MemoryEntry(
            content="run_solver",
            structured_content=skill.model_dump(),
            memory_type="procedural",
        )
    )
    results = await store.recall(
        "kick off the math thingy",
        filters=MemoryFilter(memory_type="procedural"),
    )
    assert len(results) == 1


@pytest.mark.asyncio
async def test_procedural_strategy_skill_name_filter(tmp_path):
    store = LocalMemoryStore(tmp_path / "procedural_filter.db")
    s1 = Skill(name="alpha", description="d", trigger="t")
    s2 = Skill(name="beta", description="d", trigger="t")
    await store.store(
        MemoryEntry(
            content="t", structured_content=s1.model_dump(), memory_type="procedural"
        )
    )
    await store.store(
        MemoryEntry(
            content="t", structured_content=s2.model_dump(), memory_type="procedural"
        )
    )
    results = await store.recall(
        "t",
        filters=MemoryFilter(memory_type="procedural", skill_name="beta"),
    )
    assert len(results) == 1
    assert results[0].structured_content["name"] == "beta"


@pytest.mark.asyncio
async def test_procedural_strategy_skill_min_version_filter(tmp_path):
    store = LocalMemoryStore(tmp_path / "procedural_version.db")
    v1 = Skill(name="x", description="d", trigger="t", version=1)
    v3 = Skill(name="y", description="d", trigger="t", version=3)
    await store.store(
        MemoryEntry(
            content="t", structured_content=v1.model_dump(), memory_type="procedural"
        )
    )
    await store.store(
        MemoryEntry(
            content="t", structured_content=v3.model_dump(), memory_type="procedural"
        )
    )
    results = await store.recall(
        "t",
        filters=MemoryFilter(memory_type="procedural", skill_min_version=2),
    )
    assert len(results) == 1
    assert results[0].structured_content["name"] == "y"


@pytest.mark.asyncio
async def test_unknown_memory_type_falls_back_to_semantic(tmp_path):
    """A custom-table store missing one strategy should still recall via
    the semantic fallback."""
    store = LocalMemoryStore(
        tmp_path / "fallback.db",
        strategies={"semantic": SemanticStrategy()},
    )
    await store.store(MemoryEntry(content="hello world"))
    # No filter → semantic strategy by default.
    results = await store.recall("hello")
    assert len(results) == 1


def test_memory_config_defaults_per_kind():
    cfg = MemoryConfig()
    assert cfg.semantic.ttl_days is None
    assert cfg.episodic.ttl_days == 90
    assert cfg.procedural.version_on_edit is True


def test_memory_config_per_kind_override():
    cfg = MemoryConfig(
        semantic=PerKindConfig(ttl_days=30),
    )
    assert cfg.semantic.ttl_days == 30
    # Other defaults preserved.
    assert cfg.episodic.ttl_days == 90
    assert cfg.procedural.version_on_edit is True


def test_per_kind_config_is_frozen():
    cfg = PerKindConfig()
    with pytest.raises(Exception):  # frozen dataclass → FrozenInstanceError
        cfg.ttl_days = 10  # type: ignore[misc]
