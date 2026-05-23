"""Tests for MemoryConfig."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from orqest.memory.config import MemoryConfig


class TestMemoryConfig:
    """MemoryConfig immutability and defaults."""

    def test_default_values(self) -> None:
        """Default config uses local backend with expected paths and dimensions."""
        cfg = MemoryConfig()
        assert cfg.backend == "local"
        assert cfg.local_db_path == "~/.orqest/memory.db"
        assert cfg.embedding_model == "all-MiniLM-L6-v2"
        assert cfg.embedding_dim == 384
        assert cfg.supabase_url is None
        assert cfg.supabase_key is None

    def test_custom_values(self) -> None:
        """Custom values are accepted and stored correctly."""
        cfg = MemoryConfig(
            backend="supabase",
            local_db_path="/tmp/custom.db",
            embedding_model="custom-model",
            embedding_dim=768,
            supabase_url="https://example.supabase.co",
            supabase_key="secret",
        )
        assert cfg.backend == "supabase"
        assert cfg.embedding_dim == 768
        assert cfg.supabase_url == "https://example.supabase.co"

    def test_frozen_immutable(self) -> None:
        """MemoryConfig is frozen — attribute assignment raises."""
        cfg = MemoryConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.backend = "supabase"  # type: ignore[misc]
