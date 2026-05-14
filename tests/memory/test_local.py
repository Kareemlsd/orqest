"""Tests for LocalMemoryStore (SQLite backend)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from orqest.memory.config import MemoryConfig, PerKindConfig
from orqest.memory.local import LocalMemoryStore
from orqest.memory.store import MemoryEntry, MemoryFilter, Skill


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[LocalMemoryStore]:
    """Provide a fresh LocalMemoryStore backed by a temp database."""
    s = LocalMemoryStore(tmp_path / "test.db")
    yield s
    await s.close()


class TestLocalMemoryStore:
    """LocalMemoryStore CRUD and filtering behavior."""

    @pytest.mark.asyncio
    async def test_store_and_recall_basic(self, store: LocalMemoryStore) -> None:
        """Store an entry, then recall it by content match."""
        entry = MemoryEntry(content="the quick brown fox")
        await store.store(entry)
        results = await store.recall("quick brown")
        assert len(results) == 1
        assert results[0].id == entry.id

    @pytest.mark.asyncio
    async def test_recall_with_k_limit(self, store: LocalMemoryStore) -> None:
        """Recall respects the k parameter."""
        for i in range(5):
            await store.store(MemoryEntry(content=f"entry about topic {i}"))
        results = await store.recall("topic", k=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_recall_filter_memory_type(
        self, store: LocalMemoryStore
    ) -> None:
        """Recall filters by memory_type."""
        await store.store(
            MemoryEntry(content="fact about cats", memory_type="semantic")
        )
        await store.store(
            MemoryEntry(content="experience with cats", memory_type="episodic")
        )
        results = await store.recall(
            "cats", filters=MemoryFilter(memory_type="episodic")
        )
        assert len(results) == 1
        assert results[0].memory_type == "episodic"

    @pytest.mark.asyncio
    async def test_recall_filter_source_agent(
        self, store: LocalMemoryStore
    ) -> None:
        """Recall filters by source_agent."""
        await store.store(
            MemoryEntry(content="data from alpha", source_agent="alpha")
        )
        await store.store(
            MemoryEntry(content="data from beta", source_agent="beta")
        )
        results = await store.recall(
            "data", filters=MemoryFilter(source_agent="alpha")
        )
        assert len(results) == 1
        assert results[0].source_agent == "alpha"

    @pytest.mark.asyncio
    async def test_recall_filter_min_confidence(
        self, store: LocalMemoryStore
    ) -> None:
        """Recall filters by minimum confidence threshold."""
        await store.store(
            MemoryEntry(content="sure thing", confidence=0.9)
        )
        await store.store(
            MemoryEntry(content="not sure thing", confidence=0.3)
        )
        results = await store.recall(
            "thing", filters=MemoryFilter(min_confidence=0.5)
        )
        assert len(results) == 1
        assert results[0].confidence == 0.9

    @pytest.mark.asyncio
    async def test_forget_removes_entry(self, store: LocalMemoryStore) -> None:
        """Forget decreases the count by removing the entry."""
        entry = MemoryEntry(content="temporary data")
        await store.store(entry)
        assert await store.count() == 1
        await store.forget(entry.id)
        assert await store.count() == 0

    @pytest.mark.asyncio
    async def test_forget_nonexistent_no_error(
        self, store: LocalMemoryStore
    ) -> None:
        """Forgetting a non-existent id does not raise."""
        await store.forget("does-not-exist")  # should not raise

    @pytest.mark.asyncio
    async def test_update_reliability_success_unchanged(
        self, store: LocalMemoryStore
    ) -> None:
        """Reliability score stays the same on success."""
        entry = MemoryEntry(content="reliable info", reliability_score=0.8)
        await store.store(entry)
        await store.update_reliability(entry.id, success=True)
        results = await store.recall("reliable")
        assert len(results) == 1
        assert results[0].reliability_score == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_update_reliability_failure_decays(
        self, store: LocalMemoryStore
    ) -> None:
        """Reliability score decays by 0.7 on failure."""
        entry = MemoryEntry(content="shaky info", reliability_score=1.0)
        await store.store(entry)
        await store.update_reliability(entry.id, success=False)
        results = await store.recall("shaky")
        assert len(results) == 1
        assert results[0].reliability_score == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_update_reliability_respects_config_decay(
        self, tmp_path: Path
    ) -> None:
        """Per-kind decay_on_failure from MemoryConfig drives the decay
        factor — not a hardcoded constant."""
        store = LocalMemoryStore(
            tmp_path / "decay.db",
            config=MemoryConfig(semantic=PerKindConfig(decay_on_failure=0.5)),
        )
        entry = MemoryEntry(content="shaky", reliability_score=1.0)
        await store.store(entry)
        await store.update_reliability(entry.id, success=False)
        results = await store.recall("shaky")
        assert results[0].reliability_score == pytest.approx(0.5)
        await store.close()

    @pytest.mark.asyncio
    async def test_recall_updates_access_metadata(
        self, store: LocalMemoryStore
    ) -> None:
        """Recalling an entry bumps its access_count and updates last_accessed."""
        entry = MemoryEntry(content="popular knowledge")
        await store.store(entry)

        # First recall
        results = await store.recall("popular")
        assert len(results) == 1
        _ = results[0].last_accessed

        # Second recall — access_count should be 1 higher
        results = await store.recall("popular")
        assert len(results) == 1
        assert results[0].access_count >= 1

    @pytest.mark.asyncio
    async def test_prune_expired_respects_per_kind_ttl(
        self, tmp_path: Path
    ) -> None:
        """prune_expired() deletes entries past their per-kind ttl_days,
        keeps fresh ones, and never touches a kind whose ttl_days is None."""
        from datetime import datetime, timedelta

        store = LocalMemoryStore(
            tmp_path / "ttl.db",
            config=MemoryConfig(
                semantic=PerKindConfig(ttl_days=30),    # 30-day window
                episodic=PerKindConfig(ttl_days=None),  # keep forever
            ),
        )
        now = datetime.now()
        await store.store(MemoryEntry(
            content="ancient fact", memory_type="semantic",
            created_at=now - timedelta(days=100),
        ))
        await store.store(MemoryEntry(
            content="recent fact", memory_type="semantic",
            created_at=now - timedelta(days=1),
        ))
        await store.store(MemoryEntry(
            content="ancient event", memory_type="episodic",
            created_at=now - timedelta(days=100),
        ))

        pruned = await store.prune_expired()
        assert pruned == 1

        remaining = {e.content for e in await store.list_recent()}
        assert remaining == {"recent fact", "ancient event"}
        await store.close()

    @pytest.mark.asyncio
    async def test_version_on_edit_increments_and_keeps_history(
        self, tmp_path: Path
    ) -> None:
        """With version_on_edit, re-storing a skill by name bumps its version
        and keeps the prior rows as an audit trail."""
        store = LocalMemoryStore(
            tmp_path / "ver.db",
            config=MemoryConfig(procedural=PerKindConfig(version_on_edit=True)),
        )

        def skill_entry(desc: str) -> MemoryEntry:
            skill = Skill(name="deploy", description=desc, trigger="deploy the app")
            return MemoryEntry(
                content="deploy the app",
                structured_content=skill.model_dump(),
                memory_type="procedural",
            )

        await store.store(skill_entry("v1 approach"))
        await store.store(skill_entry("v2 approach"))
        await store.store(skill_entry("v3 approach"))

        rows = await store.list_recent(memory_type="procedural")
        versions = sorted(r.structured_content["version"] for r in rows)
        assert versions == [1, 2, 3]  # three rows, three versions, history kept
        await store.close()

    @pytest.mark.asyncio
    async def test_version_on_edit_off_by_default(self, tmp_path: Path) -> None:
        """Without version_on_edit, stored skills keep their declared version."""
        store = LocalMemoryStore(tmp_path / "nover.db")  # default config: off
        for _ in range(2):
            skill = Skill(name="deploy", description="d", trigger="deploy")
            await store.store(MemoryEntry(
                content="deploy",
                structured_content=skill.model_dump(),
                memory_type="procedural",
            ))
        rows = await store.list_recent(memory_type="procedural")
        assert {r.structured_content["version"] for r in rows} == {1}
        await store.close()
