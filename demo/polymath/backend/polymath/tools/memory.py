"""Memory tools — persist + recall facts across turns.

Thin wrappers over the session's ``LocalMemoryStore`` inside the Workbench.
Reference: ``docs/concepts/memory.md``.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from orqest.memory import MemoryEntry, MemoryFilter

from polymath.runtime import emit, get_runtime
from polymath.state import PolymathState


async def _remember(
    ctx: RunContext[PolymathState],
    content: Annotated[str, "Fact or decision worth recalling later."],
    memory_type: Annotated[
        Literal["semantic", "episodic"],
        "semantic = enduring facts, episodic = this-session events.",
    ] = "episodic",
    source_agent: Annotated[str, "Which agent captured this."] = "polymath",
    confidence: Annotated[float, "0.0–1.0 self-reported confidence."] = 0.8,
) -> str:
    """Persist a fact to long-term memory.

    Emits ``memory.stored`` on success or ``memory.store_failed`` on
    error so the chrome's Memory tab can update live.
    """
    sid = ctx.deps.session_id
    store = get_runtime(sid).workbench.memory
    try:
        entry = MemoryEntry(
            content=content,
            memory_type=memory_type,
            source_agent=source_agent,
            confidence=confidence,
        )
        entry_id = await store.store(entry)
    except Exception as exc:  # noqa: BLE001 — surface as JSON error
        await emit(
            sid,
            "memory.store_failed",
            {"reason": str(exc)[:200], "memory_type": memory_type},
        )
        return json.dumps({"error": f"store failed: {exc}"})
    await emit(
        sid,
        "memory.stored",
        {
            "id": str(entry_id),
            "content": content[:240],
            "memory_type": memory_type,
            "confidence": confidence,
        },
    )
    return json.dumps({"id": str(entry_id)})


async def _recall(
    ctx: RunContext[PolymathState],
    query: Annotated[str, "Free-text query."],
    k: Annotated[int, "Maximum results to return."] = 5,
    memory_type: Annotated[
        Literal["semantic", "episodic", "any"],
        "Filter by memory kind, or 'any' for no filter.",
    ] = "any",
) -> str:
    """Search memory for matching entries.

    Emits ``memory.recalled`` (with the hit count) on every call; when
    the count is zero, also emits a typed ``memory.recall_empty`` so the
    chrome's "no hits" footer can light up.
    """
    sid = ctx.deps.session_id
    store = get_runtime(sid).workbench.memory
    mfilter = MemoryFilter(memory_type=None if memory_type == "any" else memory_type)
    hits = await store.recall(query, k=k, filters=mfilter)
    await emit(
        sid,
        "memory.recalled",
        {"query": query, "memory_type": memory_type, "k": k, "hits": len(hits)},
    )
    if not hits:
        await emit(
            sid,
            "memory.recall_empty",
            {"query": query, "memory_type": memory_type, "k": k},
        )
    return json.dumps(
        [
            {
                "id": str(h.id),
                "content": h.content,
                "memory_type": h.memory_type,
                "confidence": h.confidence,
                "reliability_score": h.reliability_score,
            }
            for h in hits
        ],
        ensure_ascii=False,
    )


remember = Tool(_remember, name="remember")
recall = Tool(_recall, name="recall")
