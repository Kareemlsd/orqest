"""Sub-agent roster endpoint — feeds the cognitive Agents tab.

The Agents tab in the right pane (`kind='agents'`) shows the session's
live sub-agent roster: every `register_agent` / `spawn_analyst` call
shows up as a row with name, role, tools, and the most recent
invocation outcome. The ``GET /sessions/{sid}/agents/roster`` endpoint
hydrates the tab on mount; SSE ``agent.*`` events keep it live.

Sub-agents persist as procedural :class:`MemoryEntry` records (see
:mod:`polymath.tools.autonomy`); we read directly from
``LocalMemoryStore.list_recent(memory_type='procedural')`` rather than
calling :func:`_list_agents` to avoid going through the agent-tool
machinery on a synchronous read path.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from polymath.runtime import get_runtime

router = APIRouter(prefix="/sessions", tags=["autonomy"])


def _serialize(entry: Any) -> dict[str, Any] | None:
    """Project a procedural :class:`MemoryEntry` to a roster row.

    Returns ``None`` when the entry isn't actually a sub-agent record
    (procedural memory hosts other skills too — only entries with an
    ``agent_spec`` blob in metadata are real sub-agents).
    """
    meta = entry.metadata or {}
    if "agent_spec" not in meta:
        return None
    skill = entry.structured_content
    skill_dict: dict[str, Any] = {}
    if skill is not None:
        if hasattr(skill, "model_dump"):
            try:
                skill_dict = skill.model_dump(mode="json")
            except Exception:  # noqa: BLE001
                skill_dict = {}
        elif isinstance(skill, dict):
            skill_dict = skill
    spec_payload = meta.get("agent_spec") or {}
    # Tool list: prefer the recorded tool_sequence (the skill's known
    # working order) but fall back to the agent spec's declared tools.
    seq = skill_dict.get("tool_sequence") or skill_dict.get("steps") or []
    tool_names = [s.get("tool_name") for s in seq if isinstance(s, dict) and s.get("tool_name")]
    if not tool_names:
        tool_names = [
            t.get("name")
            for t in (spec_payload.get("tools") or [])
            if isinstance(t, dict) and t.get("name")
        ]
    created = entry.created_at
    last_accessed = entry.last_accessed
    return {
        "name": skill_dict.get("name", entry.content),
        "role": meta.get("role", skill_dict.get("description", "")),
        "model": spec_payload.get("model"),
        "tools": tool_names,
        "tool_count": len(tool_names),
        "reliability_score": entry.reliability_score,
        "access_count": entry.access_count,
        "created_at": created.isoformat() if created else None,
        "last_invoked_at": last_accessed.isoformat() if last_accessed else None,
    }


@router.get("/{sid}/agents/roster")
async def get_roster(sid: UUID, limit: int = 50) -> dict[str, Any]:
    """Return the registered sub-agents for the session.

    Best-effort: missing memory store, query failures, or no
    procedural entries all yield an empty roster instead of a 5xx.
    """
    runtime = get_runtime(str(sid))
    store = runtime.workbench.memory
    try:
        entries = await store.list_recent(memory_type="procedural", limit=limit)
    except Exception:  # noqa: BLE001
        entries = []
    rows: list[dict[str, Any]] = []
    for entry in entries:
        row = _serialize(entry)
        if row is not None:
            rows.append(row)
    return {"agents": rows, "count": len(rows)}
