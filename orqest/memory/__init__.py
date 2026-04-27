"""Memory subsystem for orqest agents.

Provides a pluggable memory protocol (MemoryStore) with a local SQLite backend.
Three cognitive memory kinds are first-class:

* **semantic** — what's true (facts, summaries)
* **episodic** — what happened (sessions, traces)
* **procedural** — how to do things (skills via :class:`Skill`)
"""

from orqest.memory.config import MemoryConfig, PerKindConfig
from orqest.memory.local import LocalMemoryStore
from orqest.memory.store import (
    MemoryEntry,
    MemoryFilter,
    MemoryStore,
    Skill,
    SkillExample,
    ToolCallSpec,
)
from orqest.memory.strategies import (
    EpisodicStrategy,
    ProceduralStrategy,
    RetrievalStrategy,
    SemanticStrategy,
    default_strategy_table,
)

__all__ = [
    "EpisodicStrategy",
    "LocalMemoryStore",
    "MemoryConfig",
    "MemoryEntry",
    "MemoryFilter",
    "MemoryStore",
    "PerKindConfig",
    "ProceduralStrategy",
    "RetrievalStrategy",
    "SemanticStrategy",
    "Skill",
    "SkillExample",
    "ToolCallSpec",
    "default_strategy_table",
]
