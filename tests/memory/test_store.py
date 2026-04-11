"""Tests for MemoryEntry and MemoryFilter data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.memory.store import MemoryEntry, MemoryFilter


class TestMemoryEntry:
    """MemoryEntry model validation and behavior."""

    def test_generates_uuid_by_default(self) -> None:
        """A new MemoryEntry gets a unique UUID id without explicit assignment."""
        entry_a = MemoryEntry(content="hello")
        entry_b = MemoryEntry(content="world")
        assert entry_a.id != entry_b.id
        assert len(entry_a.id) == 36  # UUID4 string length

    def test_confidence_rejects_out_of_bounds(self) -> None:
        """Confidence must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            MemoryEntry(content="bad", confidence=1.5)
        with pytest.raises(ValidationError):
            MemoryEntry(content="bad", confidence=-0.1)

    def test_reliability_rejects_out_of_bounds(self) -> None:
        """Reliability score must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            MemoryEntry(content="bad", reliability_score=2.0)
        with pytest.raises(ValidationError):
            MemoryEntry(content="bad", reliability_score=-0.5)

    def test_serialization_round_trip(self) -> None:
        """An entry survives JSON serialization and deserialization."""
        original = MemoryEntry(
            content="test content",
            memory_type="episodic",
            source_agent="agent-1",
            confidence=0.8,
            metadata={"key": "value"},
        )
        data = original.model_dump_json()
        restored = MemoryEntry.model_validate_json(data)
        assert restored.id == original.id
        assert restored.content == original.content
        assert restored.memory_type == original.memory_type
        assert restored.metadata == original.metadata


class TestMemoryFilter:
    """MemoryFilter model behavior."""

    def test_all_none_fields_matches_everything(self) -> None:
        """A default MemoryFilter with all None fields imposes no constraints."""
        f = MemoryFilter()
        assert f.memory_type is None
        assert f.source_agent is None
        assert f.min_confidence is None
        assert f.min_reliability is None
