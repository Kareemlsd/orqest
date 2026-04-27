"""Memory subsystem configuration.

Provides MemoryConfig as an immutable container for memory backend settings.
Follows the same frozen-dataclass pattern as OrqestConfig.

Per-kind policies (TTL, decay, version-on-edit) live in
:class:`PerKindConfig` instances on :class:`MemoryConfig`. Defaults
preserve v0.0.1 behavior — semantic and episodic policies match the
inline behavior of :class:`LocalMemoryStore`; procedural defaults to
``version_on_edit=True`` to give skill versioning out of the box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PerKindConfig:
    """Per-kind retention/decay/versioning policy.

    Defaults match the v0.0.1 behavior so existing semantic/episodic
    callers see no change.
    """

    ttl_days: int | None = None
    """``None`` means forever; otherwise entries past this age are
    eligible for pruning during maintenance."""
    decay_on_failure: float = 0.7
    """Reliability multiplier on failed-recall reports."""
    prune_below: float = 0.1
    """Reliability floor below which an entry is pruned."""
    version_on_edit: bool = False
    """When True, storing an entry whose
    ``structured_content.name`` matches an existing entry increments
    ``version`` rather than overwriting. Used by procedural memory to
    keep an audit of skill revisions."""


def _episodic_default() -> PerKindConfig:
    return PerKindConfig(ttl_days=90)


def _procedural_default() -> PerKindConfig:
    return PerKindConfig(version_on_edit=True)


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
    episodic: PerKindConfig = field(default_factory=_episodic_default)
    procedural: PerKindConfig = field(default_factory=_procedural_default)
