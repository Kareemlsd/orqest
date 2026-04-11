"""Memory subsystem configuration.

Provides MemoryConfig as an immutable container for memory backend settings.
Follows the same frozen-dataclass pattern as OrqestConfig.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MemoryConfig:
    """Immutable configuration for the memory subsystem."""

    backend: Literal["local", "supabase"] = "local"
    local_db_path: str = "~/.orqest/memory.db"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    supabase_url: str | None = None
    supabase_key: str | None = None
