"""Sub-agent roster tools — backed by procedural memory.

Three orchestrator-facing tools manage a session-scoped sub-agent
roster persisted in the workbench's :class:`~orqest.memory.LocalMemoryStore`
(memory_type=``"procedural"``). Consolidating onto Orqest's procedural
memory replaces the bespoke ``SubAgent`` SQLModel table that predated
Wave 1.2.

* ``register_agent(name, role, system_prompt, …)`` — define a named
  sub-agent once. Idempotent: re-registering with the same name updates
  the existing skill (procedural entries are INSERT-OR-REPLACE keyed on
  ``MemoryEntry.id`` — we use a deterministic id derived from the name).
* ``invoke_agent(name, prompt, context?)`` — recall the persisted
  :class:`Skill` entry, rehydrate the embedded :class:`AgentSpec`, and
  spawn a live :class:`DynamicAgent`. Uses ``run_enriched`` so the
  result carries metacognition fields (``confidence`` /
  ``uncertainty_targets`` / ``capability_boundary``).
* ``list_agents()`` — recall every procedural entry in the session's
  memory store and project each into the legacy JSON shape.

A ``spawn_analyst`` shim is preserved for backwards compatibility — it
ensures an ``analyst`` is registered with the canned defaults and then
invokes it.

**Design note — where the AgentSpec lives.** The :class:`Skill` shape
captures the *behaviour* (trigger / tool sequence / outcome). The
:class:`AgentSpec` captures the *agent definition* (system prompt,
output schema, model). They overlap but aren't equivalent. We store
the spec in :attr:`MemoryEntry.metadata` under the key ``"agent_spec"``
rather than wedging it into ``success_examples`` (which is reserved for
worked invocations) or ``ToolCallSpec`` (which is one step, not a full
agent contract). This keeps the Skill model semantically clean.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import uuid4

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from orqest.agents.state import GlobalState
from orqest.autonomy import AgentFactory, AgentSpec, ToolSpec
from orqest.memory import MemoryEntry, MemoryFilter, Skill, ToolCallSpec
from orqest.metacognition import StructuredOutputProtocol

from polymath.autonomy.analyst import (
    build_analyst_spec,
    build_session_registry,
)
from polymath.config import get_default_config
from polymath.runtime import emit, get_runtime
from polymath.state import PolymathState

_MAX_PROMPT_CHARS = 8000
_ALLOWED_TOOLS = {"web_search", "web_fetch"}


def _build_factory() -> AgentFactory:
    cfg = get_default_config()
    return AgentFactory(
        registry=build_session_registry(),
        default_model=cfg.LLM_MODEL,
        api_key=cfg.require_llm_key(),
    )


def _entry_id_for(session_id: str, name: str) -> str:
    """Deterministic memory-entry id so re-registering updates in place.

    Procedural entries do not natively support upsert-by-name; SQLite
    persistence is keyed on ``MemoryEntry.id``. Hashing
    ``(session_id, name)`` gives us idempotent re-registration without
    a separate read-then-update round trip.
    """
    digest = hashlib.sha1(f"{session_id}:{name}".encode()).hexdigest()
    return f"sub-agent-{digest[:24]}"


def _skill_for(name: str, role: str, tools: list[str]) -> Skill:
    """Build the :class:`Skill` that wraps a sub-agent registration.

    *role* lands in ``description``. *name* is also the trigger so
    procedural recall via the trigger field finds it; ``invoke_agent``
    queries by ``skill_name`` for an exact match regardless.
    """
    return Skill(
        name=name,
        description=role,
        trigger=name,
        tool_sequence=[ToolCallSpec(tool_name=t) for t in tools],
        expected_outcome=(
            "Structured analyst-style report (summary / findings / next_steps) "
            "with optional metacognition fields (self_confidence / "
            "uncertain_about / outside_my_capability)."
        ),
    )


def _build_spec(
    *,
    name: str,
    role: str,
    system_prompt: str,
    tools: list[str] | None = None,
    model: str | None = None,
    constraints: list[str] | None = None,
) -> AgentSpec:
    """Construct an :class:`AgentSpec` with the canonical analyst-style
    output schema (``summary`` / ``findings`` / ``next_steps``) plus the
    optional metacognition fields read by
    :class:`StructuredOutputProtocol`.
    """
    cfg = get_default_config()
    return AgentSpec(
        name=name,
        system_prompt=system_prompt,
        output_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "findings": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}},
                # Optional metacognition fields — present so the analyst
                # *can* self-report, not required so existing demos still
                # validate without them.
                "self_confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": (
                        "Self-rated probability that the analysis satisfies "
                        "the goal."
                    ),
                },
                "uncertain_about": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Free-text identifiers for the assumptions/sub-claims "
                        "that bottlenecked your confidence."
                    ),
                },
                "outside_my_capability": {
                    "type": "boolean",
                    "description": (
                        "True iff the goal is outside what you can verify "
                        "(missing tool, post-cutoff knowledge, subjective "
                        "judgement)."
                    ),
                },
            },
            "required": ["summary", "findings"],
        },
        tools=[ToolSpec(name=t, description="") for t in (tools or [])],
        model=model or cfg.LLM_MODEL,
        constraints=constraints or [],
        metadata={"role": role},
    )


async def _store_sub_agent(
    *,
    session_id: str,
    name: str,
    role: str,
    spec: AgentSpec,
) -> tuple[bool, str]:
    """Persist the sub-agent as a procedural :class:`MemoryEntry`.

    Returns ``(created, action)``. ``action`` is ``"registered"`` when
    no existing entry was found, ``"updated"`` otherwise.
    """
    workbench = get_runtime(session_id).workbench
    existing = await workbench.memory.recall(
        query=name,
        k=1,
        filters=MemoryFilter(memory_type="procedural", skill_name=name),
    )
    skill = _skill_for(name=name, role=role, tools=[t.name for t in spec.tools])
    entry = MemoryEntry(
        id=_entry_id_for(session_id, name),
        content=name,
        structured_content=skill.model_dump(),
        memory_type="procedural",
        source_agent="polymath",
        metadata={
            "role": role,
            "agent_spec": spec.model_dump(),
            "session_id": session_id,
        },
    )
    await workbench.memory.store(entry)
    if existing:
        return False, "updated"
    return True, "registered"


async def _recall_sub_agent(
    session_id: str, name: str
) -> tuple[MemoryEntry, AgentSpec] | None:
    """Recall a previously-registered sub-agent and rehydrate its spec."""
    workbench = get_runtime(session_id).workbench
    hits = await workbench.memory.recall(
        query=name,
        k=1,
        filters=MemoryFilter(memory_type="procedural", skill_name=name),
    )
    if not hits:
        return None
    entry = hits[0]
    spec_payload = (entry.metadata or {}).get("agent_spec")
    if not spec_payload:
        return None
    spec = AgentSpec.model_validate(spec_payload)
    return entry, spec


# ---- register_agent ---------------------------------------------------


async def _register_agent(
    ctx: RunContext[PolymathState],
    name: Annotated[
        str,
        "Short stable identifier. Reuse the same name to update an "
        "existing sub-agent (e.g. 'analyst', 'bench_runner').",
    ],
    role: Annotated[str, "One-sentence human description of this sub-agent's job."],
    system_prompt: Annotated[
        str,
        "Persona + behaviour for the sub-agent. It does NOT see the "
        "orchestrator's conversation, so be self-contained.",
    ],
    tools: Annotated[
        list[str] | None,
        "Optional tool names from the shared registry (currently "
        "'web_search', 'web_fetch'). Empty / omitted = pure structured "
        "output specialist.",
    ] = None,
) -> str:
    """Persist a named sub-agent for this session (procedural memory)."""
    sid = ctx.deps.session_id
    safe_tools = [t for t in (tools or []) if t in _ALLOWED_TOOLS]
    spec = _build_spec(
        name=name,
        role=role,
        system_prompt=system_prompt,
        tools=safe_tools,
    )
    _, action = await _store_sub_agent(
        session_id=sid, name=name, role=role, spec=spec
    )
    await emit(
        sid,
        f"agent.{action}",
        {"name": name, "role": role, "tools": safe_tools},
    )
    return json.dumps(
        {
            "ok": True,
            "action": action,
            "name": name,
            "role": role,
            "tools": safe_tools,
        }
    )


# ---- invoke_agent -----------------------------------------------------


async def _invoke_agent(
    ctx: RunContext[PolymathState],
    name: Annotated[str, "Name of a previously-registered sub-agent."],
    prompt: Annotated[
        str,
        "Self-contained instruction for this invocation. The sub-agent "
        "does not see the orchestrator's conversation.",
    ],
    context: Annotated[
        str, "Optional supporting notes appended below the prompt."
    ] = "",
) -> str:
    """Run the named sub-agent once and return its structured report.

    Uses :meth:`BaseAgent.run_enriched` with
    :class:`StructuredOutputProtocol` so the JSON payload includes
    metacognition fields (``confidence`` / ``uncertainty_targets`` /
    ``capability_boundary``) when the sub-agent self-reports them.
    """
    sid = ctx.deps.session_id
    run_id = uuid4().hex[:8]

    found = await _recall_sub_agent(sid, name)
    if found is None:
        await emit(
            sid,
            "agent.invocation_failed",
            {"name": name, "reason": "not_registered"},
        )
        return json.dumps(
            {"error": f"no sub-agent named '{name}' — call register_agent first"}
        )
    entry, spec = found
    role = (entry.metadata or {}).get("role", "")

    full = prompt if not context else f"{prompt}\n\nContext:\n{context}"
    if len(full) > _MAX_PROMPT_CHARS:
        full = full[:_MAX_PROMPT_CHARS] + "\n…[truncated]"

    await emit(
        sid,
        "agent.spawned",
        {
            "run_id": run_id,
            "name": spec.name,
            "role": role,
            "model": spec.model,
            "tool_count": len(spec.tools),
            "persistent": True,
        },
    )

    try:
        agent = _build_factory().spawn(spec)
        # TODO: AgentFactory.spawn currently has no kwarg for
        # confidence_protocol — inject after the fact. Tighten once
        # factory support lands.
        agent._confidence_protocol = StructuredOutputProtocol()
        state = GlobalState()
        state.add_message("user", full)
        enriched = await agent.run_enriched(state)
        output = enriched.output
    except Exception as exc:  # noqa: BLE001 — surface as JSON
        await emit(
            sid,
            "agent.completed",
            {"run_id": run_id, "name": spec.name, "ok": False, "error": str(exc)},
        )
        return json.dumps({"error": f"sub-agent '{name}' failed: {exc}"})

    payload = output.model_dump() if hasattr(output, "model_dump") else dict(output)
    await emit(
        sid,
        "agent.completed",
        {
            "run_id": run_id,
            "name": spec.name,
            "ok": True,
            "summary": payload.get("summary", ""),
            "finding_count": len(payload.get("findings", []) or []),
            "confidence": enriched.confidence,
            "capability_boundary": enriched.capability_boundary,
        },
    )
    return json.dumps(
        {
            "run_id": run_id,
            "agent": name,
            "report": payload,
            "confidence": enriched.confidence,
            "uncertainty_targets": list(enriched.uncertainty_targets),
            "capability_boundary": enriched.capability_boundary,
        }
    )


# ---- list_agents ------------------------------------------------------


async def _list_agents(ctx: RunContext[PolymathState]) -> str:
    """Return the session's sub-agent roster (read from procedural memory)."""
    sid = ctx.deps.session_id
    workbench = get_runtime(sid).workbench
    hits = await workbench.memory.recall(
        query="",
        k=50,
        filters=MemoryFilter(memory_type="procedural"),
    )
    agents: list[dict] = []
    for h in hits:
        meta = h.metadata or {}
        # Only include entries that originated from this consolidation
        # (carry an ``agent_spec`` payload). Other procedural skills in
        # the same session — should any land — pass through unaffected.
        if "agent_spec" not in meta:
            continue
        skill = h.structured_content or {}
        spec_payload = meta.get("agent_spec") or {}
        tool_names = [
            t["tool_name"] for t in skill.get("tool_sequence", []) if "tool_name" in t
        ]
        if not tool_names:
            tool_names = [t.get("name") for t in spec_payload.get("tools", [])]
        agents.append(
            {
                "name": skill.get("name", h.content),
                "role": meta.get("role", skill.get("description", "")),
                "tools": tool_names,
                "created_at": h.created_at.isoformat(),
                "updated_at": h.last_accessed.isoformat(),
            }
        )
    return json.dumps({"agents": agents})


# ---- spawn_analyst — back-compat one-shot -----------------------------


async def _spawn_analyst(
    ctx: RunContext[PolymathState],
    goal: Annotated[str, "Self-contained instruction for the analyst."],
    context: Annotated[str, "Optional supporting notes."] = "",
) -> str:
    """One-shot analyst: ensures an ``analyst`` is registered with the
    canned defaults, then invokes it. Prefer the explicit
    ``register_agent`` + ``invoke_agent`` pair when you want roster
    control."""
    sid = ctx.deps.session_id
    if await _recall_sub_agent(sid, "analyst") is None:
        default = build_analyst_spec(goal=goal)
        await _store_sub_agent(
            session_id=sid,
            name="analyst",
            role="general-purpose structured-output analyst",
            spec=default,
        )
        await emit(
            sid,
            "agent.registered",
            {
                "name": "analyst",
                "role": "general-purpose structured-output analyst",
                "tools": ["web_search", "web_fetch"],
            },
        )
    return await _invoke_agent(ctx, name="analyst", prompt=goal, context=context)


register_agent = Tool(_register_agent, name="register_agent")
invoke_agent = Tool(_invoke_agent, name="invoke_agent")
list_agents = Tool(_list_agents, name="list_agents")
spawn_analyst = Tool(_spawn_analyst, name="spawn_analyst")
