"""Memory subsystem configuration.

Provides MemoryConfig as an immutable container for memory backend settings.
Follows the same frozen-dataclass pattern as OrqestConfig.

Per-kind policy (decay-on-failure, prune floor, retention TTL) lives in
:class:`PerKindConfig` instances on :class:`MemoryConfig`, one per
cognitive memory kind. :class:`~orqest.memory.local.LocalMemoryStore`
reads ``decay_on_failure`` / ``prune_below`` in ``update_reliability``
and ``ttl_days`` in ``prune_expired``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PerKindConfig:
    """Per-kind reliability / retention policy."""

    decay_on_failure: float = 0.7
    """Reliability multiplier applied on a failed-recall report."""
    prune_below: float = 0.1
    """Reliability floor below which an entry is pruned after decay."""
    ttl_days: int | None = None
    """Retention window. ``None`` means keep forever; otherwise entries
    older than this are deleted by :meth:`LocalMemoryStore.prune_expired`."""


@dataclass(frozen=True)
class MemoryConfig:
    """Immutable configuration for the memory subsystem."""

    backend: Literal["local", "supabase"] = "local"
    local_db_path: str = "~/.orqest/memory.db"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    supabase_url: str | None = None
    supabase_key: str | None = None
    semantic: PerKindConfig = field(default_factory=PerKindConfig)
    episodic: PerKindConfig = field(default_factory=PerKindConfig)
    procedural: PerKindConfig = field(default_factory=PerKindConfig)
