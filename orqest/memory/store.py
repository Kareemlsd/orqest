"""Memory storage protocol and data models.

Defines the MemoryStore protocol for pluggable memory backends, along with
MemoryEntry (the unit of stored knowledge) and MemoryFilter (query-time
constraints). Backends implement MemoryStore; callers depend only on the protocol.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryFilter(BaseModel):
    """Query-time constraints for memory recall."""

    memory_type: Literal["semantic", "episodic"] | None = None
    source_agent: str | None = None
    min_confidence: float | None = None
    min_reliability: float | None = None


class MemoryEntry(BaseModel):
    """A single unit of stored knowledge."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    memory_type: Literal["semantic", "episodic"] = "semantic"
    source_agent: str = "unknown"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    last_accessed: datetime = Field(default_factory=datetime.now)
    access_count: int = 0
    reliability_score: float = Field(default=1.0, ge=0.0, le=1.0)


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
