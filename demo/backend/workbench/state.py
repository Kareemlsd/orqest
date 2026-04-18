"""Shared in-process state for the Workbench demo.

A single-process demo holds its memory store, tracer, event bus, and
session state in module-level globals for simplicity. Production apps
would put these behind dependency injection / per-request lifecycle.
"""

from __future__ import annotations

import tempfile
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orqest.memory import LocalMemoryStore, MemoryEntry
from orqest.observability import AgentEvent, EventBus, JSONTracer

# Memory — persisted per-session in the system temp dir for the demo.
# Production: configure path via env, or use the Supabase backend when available.
_memory_path = Path(tempfile.gettempdir()) / "orqest-workbench-memory.db"
memory = LocalMemoryStore(db_path=_memory_path)

# Tracer and event bus are process-wide for this demo.
tracer = JSONTracer()
event_bus = EventBus()

# A bounded ring-buffer of recent events so the frontend can fetch them
# via /api/workbench/events even if it missed the live stream.
_EVENT_BUFFER_SIZE = 200
recent_events: deque[dict[str, Any]] = deque(maxlen=_EVENT_BUFFER_SIZE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _record_event(event: AgentEvent) -> None:
    """Global event subscriber that snapshots events for the frontend."""
    recent_events.append(
        {
            "event_type": event.event_type,
            "agent_name": event.agent_name,
            "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
            "data": event.data,
            "span_id": event.span_id,
            "trace_id": event.trace_id,
        }
    )


# Subscribe once at module load.
event_bus.subscribe_all(_record_event)


def reset_session() -> None:
    """Clear traces + events for a fresh session. Memory persists."""
    tracer.clear()
    recent_events.clear()


def snapshot_trace() -> list[dict[str, Any]]:
    """Export all current spans as JSON-safe dicts."""
    return tracer.export_json()


def snapshot_events() -> list[dict[str, Any]]:
    """Return the recent-events ring buffer."""
    return list(recent_events)


async def snapshot_memories(limit: int = 30) -> list[dict[str, Any]]:
    """Return the most recent memories as JSON-safe dicts.

    LocalMemoryStore's ``recall`` uses FTS5 so an empty query returns
    nothing. For a "list all" view we read directly from the SQLite
    connection behind the store — this is a demo-specific coupling,
    documented so we replace it if the MemoryStore protocol grows a
    ``list_all`` method.
    """
    db = await memory._ensure_db()  # noqa: SLF001 — demo coupling
    async with db.execute(
        "SELECT id, content, memory_type, source_agent, confidence, "
        "metadata, created_at, reliability_score, access_count "
        "FROM memories ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ) as cursor:
        rows = await cursor.fetchall()

    import json as _json
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            meta = _json.loads(row[5]) if row[5] else {}
        except Exception:  # noqa: BLE001
            meta = {}
        result.append(
            {
                "id": row[0],
                "content": row[1],
                "memory_type": row[2],
                "source_agent": row[3],
                "confidence": row[4],
                "metadata": meta,
                "created_at": row[6],
                "reliability_score": row[7],
                "access_count": row[8],
            }
        )
    return result


async def forget_memory(entry_id: str) -> None:
    """Delete a memory entry by id."""
    await memory.forget(entry_id)
