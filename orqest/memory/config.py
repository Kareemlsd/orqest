"""Memory subsystem configuration.

Provides MemoryConfig as an immutable container for memory backend settings.
Follows the same frozen-dataclass pattern as OrqestConfig.

Per-kind policy (decay-on-failure, prune floor, retention TTL,
version-on-edit) lives in :class:`PerKindConfig` instances on
:class:`MemoryConfig`, one per cognitive memory kind.
:class:`~orqest.memory.local.LocalMemoryStore` reads ``decay_on_failure`` /
``prune_below`` in ``update_reliability``, ``ttl_days`` in
``prune_expired``, and ``version_on_edit`` in ``store``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PerKindConfig:
    """Per-kind reliability / retention / versioning policy."""

    decay_on_failure: float = 0.7
    """Reliability multiplier applied on a failed-recall report."""
    prune_below: float = 0.1
    """Reliability floor below which an entry is pruned after decay."""
    ttl_days: int | None = None
    """Retention window. ``None`` means keep forever; otherwise entries
    older than this are deleted by :meth:`LocalMemoryStore.prune_expired`."""
    version_on_edit: bool = False
    """When True, storing a procedural entry whose ``structured_content.name``
    matches an already-stored skill bumps the new entry's ``version`` one past
    the highest stored version and keeps the prior rows — an audit trail."""


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
    tool: PerKindConfig = field(
        default_factory=lambda: PerKindConfig(
            ttl_days=None,            # tools don't auto-expire
            version_on_edit=True,     # re-promotion of same name bumps version
            decay_on_failure=0.5,     # aggressive decay — bad tools are bad
        )
    )
