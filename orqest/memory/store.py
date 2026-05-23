"""Memory storage protocol and data models.

Defines the MemoryStore protocol for pluggable memory backends, along with
MemoryEntry (the unit of stored knowledge) and MemoryFilter (query-time
constraints). Backends implement MemoryStore; callers depend only on the protocol.

Supports four cognitive memory kinds:

* **semantic** — what's true (facts, summaries, learned content)
* **episodic** — what happened (sessions, traces, prior runs)
* **procedural** — how to do things (skills, recipes, learned tool sequences)
* **tool** — runtime-authored tool implementations (host-side mirror of
  the in-container SQLite tool library that the Tier-2
  :class:`DockerSandbox` persists per-user). The ``structured_content``
  carries a :class:`GeneratedToolSpec`-shaped dict.

Procedural entries carry a structured ``Skill`` payload in
``MemoryEntry.structured_content``; the searchable trigger text lives in
``MemoryEntry.content`` so FTS5 indexing keeps working uniformly.

Tool entries carry a ``GeneratedToolSpec``-shaped dict in
``structured_content`` (with ``name``, ``description``, ``parameters``,
``implementation``, ``allowed_imports``, ``dependencies``). ``content``
is the tool description (FTS-indexable). They are looked up by exact
name rather than similarity — see :class:`ToolStrategy`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


# ---- Procedural memory shape ------------------------------------------


class ToolCallSpec(BaseModel):
    """One step in a Skill's tool_sequence."""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class SkillExample(BaseModel):
    """A worked example of a successful Skill invocation."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.now)


class Skill(BaseModel):
    """Procedural memory content — a learned tool sequence with outcome.

    Stored inside :class:`MemoryEntry.structured_content` when
    ``memory_type == "procedural"``. The ``trigger`` field is the
    natural-language phrase the agent matches against to decide whether
    to invoke the skill; it is also written verbatim into
    :class:`MemoryEntry.content` so FTS5 still indexes it.
    """

    name: str
    description: str
    trigger: str
    tool_sequence: list[ToolCallSpec] = Field(default_factory=list)
    expected_outcome: str = ""
    success_examples: list[SkillExample] = Field(default_factory=list)
    version: int = 1


# ---- MemoryFilter / MemoryEntry ---------------------------------------


class MemoryFilter(BaseModel):
    """Query-time constraints for memory recall."""

    memory_type: Literal["semantic", "episodic", "procedural", "tool"] | None = None
    source_agent: str | None = None
    min_confidence: float | None = None
    min_reliability: float | None = None
    skill_name: str | None = None
    """Exact-match on ``structured_content.name`` — only applies when
    ``memory_type == "procedural"``. No-op otherwise."""
    skill_min_version: int | None = None
    """Filter procedural entries to ``version >= skill_min_version``."""


class MemoryEntry(BaseModel):
    """A single unit of stored knowledge."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    structured_content: dict[str, Any] | None = None
    """Typed payload for non-text memory (e.g. ``Skill`` for procedural).
    When ``memory_type == "procedural"`` and this field is set, it must
    validate against the :class:`Skill` schema. Validation is gated to
    procedural entries to keep the legacy semantic/episodic paths
    untouched."""
    memory_type: Literal["semantic", "episodic", "procedural", "tool"] = "semantic"
    source_agent: str = "unknown"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    last_accessed: datetime = Field(default_factory=datetime.now)
    access_count: int = 0
    reliability_score: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_procedural_shape(self) -> MemoryEntry:
        """Enforce the :class:`Skill` shape on procedural entries — strict.

        Construction-time validation: if ``memory_type == "procedural"``
        and ``structured_content`` is set but not Skill-shaped, this
        raises :class:`pydantic.ValidationError`. Garbage in is rejected
        at the data-model boundary so the storage layer can stay
        best-effort about *I/O* failures without papering over malformed
        payloads.

        Semantic / episodic entries (or procedural entries with no
        ``structured_content``) skip this check — the legacy plain-text
        path is unaffected.
        """
        if self.memory_type == "procedural" and self.structured_content is not None:
            Skill.model_validate(self.structured_content)
        return self


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol for pluggable memory backends.

    Implementations must provide async store, recall, forget,
    update_reliability, and count operations.
    """

    async def store(self, entry: MemoryEntry) -> str:
        """Persist a memory entry and return its id."""
        ...

    async def recall(
        self,
        query: str,
        *,
        k: int = 5,
        filters: MemoryFilter | None = None,
    ) -> list[MemoryEntry]:
        """Retrieve the top-k entries matching the query and optional filters."""
        ...

    async def forget(self, entry_id: str) -> None:
        """Remove a memory entry by id. No error if not found."""
        ...

    async def update_reliability(self, entry_id: str, *, success: bool) -> None:
        """Adjust an entry's reliability score based on outcome."""
        ...

    async def count(self) -> int:
        """Return the total number of stored entries."""
        ...
