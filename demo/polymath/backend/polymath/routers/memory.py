"""Memory inspector endpoint — feeds the cognitive Memory tab.

The Memory tab in the right pane (`kind='memory'`) is a browse-style
view over the session's :class:`~orqest.memory.LocalMemoryStore`,
grouped by typology (semantic / episodic / procedural). The
``GET /sessions/{sid}/memory`` endpoint hydrates the tab on mount; SSE
``memory.*`` events keep it live without re-fetching.

Returned shape:

```
{
  "semantic":   { "count": <int>, "entries": [<MemoryRow>, ...] },
  "episodic":   { "count": <int>, "entries": [<MemoryRow>, ...] },
  "procedural": { "count": <int>, "entries": [<MemoryRow>, ...] }
}
```

Each ``MemoryRow`` carries enough for the section list to render
without extra round-trips: id, content (truncated at the source for
the chrome), memory_type, source_agent, confidence, reliability_score,
created_at, structured_content (for procedural skill steps).

The endpoint is intentionally per-session (not global): each session
has its own SQLite memory file at ``cfg.MEMORY_DIR/{sid}.db``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from polymath.runtime import get_runtime

router = APIRouter(prefix="/sessions", tags=["memory"])


_KINDS: tuple[str, ...] = ("semantic", "episodic", "procedural")


def _serialize(entry: Any) -> dict[str, Any]:
    """Project a :class:`MemoryEntry` to the JSON the chrome consumes."""
    structured = getattr(entry, "structured_content", None)
    structured_payload: Any = None
    if structured is not None:
        # ``structured_content`` may be a Pydantic model (Skill) or a raw dict.
        if hasattr(structured, "model_dump"):
            try:
                structured_payload = structured.model_dump(mode="json")
            except Exception:  # noqa: BLE001
                structured_payload = None
        elif isinstance(structured, dict):
            structured_payload = structured
    created = getattr(entry, "created_at", None)
    last_accessed = getattr(entry, "last_accessed", None)
    return {
        "id": str(getattr(entry, "id", "")),
        "content": getattr(entry, "content", ""),
        "memory_type": getattr(entry, "memory_type", "semantic"),
        "source_agent": getattr(entry, "source_agent", None),
        "confidence": getattr(entry, "confidence", None),
        "reliability_score": getattr(entry, "reliability_score", None),
        "access_count": getattr(entry, "access_count", 0),
        "created_at": created.isoformat() if created else None,
        "last_accessed_at": last_accessed.isoformat() if last_accessed else None,
        "structured_content": structured_payload,
    }


@router.get("/{sid}/memory")
async def list_memory(sid: UUID, limit: int = 50) -> dict[str, Any]:
    """Return memory entries grouped by typology.

    The chrome's three-section browser reads each kind's
    ``{count, entries}`` block independently. Best-effort: a missing /
    unreadable memory store yields empty sections rather than a 5xx so
    the tab can still render its empty state.
    """
    runtime = get_runtime(str(sid))
    store = runtime.workbench.memory
    sections: dict[str, dict[str, Any]] = {}
    for kind in _KINDS:
        try:
            entries = await store.list_recent(memory_type=kind, limit=limit)
        except Exception:  # noqa: BLE001
            entries = []
        sections[kind] = {
            "count": len(entries),
            "entries": [_serialize(e) for e in entries],
        }
    return sections
