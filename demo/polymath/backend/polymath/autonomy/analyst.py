"""Analyst sub-agent — runtime-spawned via :class:`orqest.AgentFactory`.

The orchestrator delegates a focused analysis sub-task to the analyst by
calling :func:`build_analyst_spec`, which produces a serializable
:class:`~orqest.autonomy.AgentSpec`. The factory hydrates that into a
live :class:`~orqest.autonomy.DynamicAgent` with a typed output model.

The analyst is deliberately tool-light: it is a structured-output
specialist that turns notes/findings into a typed report. The
orchestrator already has the sandbox tools — handing them to the
analyst would just create surface area without buying capability.
"""

from __future__ import annotations

from pydantic_ai import Tool

from orqest.autonomy import AgentSpec, AgentFactory, ToolRegistry, ToolSpec
from orqest.tools.web import web_fetch, web_search

from polymath.config import get_default_config

_SYSTEM_PROMPT = (
    "You are Polymath's analyst sub-agent. The orchestrator delegates "
    "focused analysis to you. Read the goal carefully, use web tools "
    "only if you genuinely need fresh data, and return a structured "
    "report. Be concise and concrete: short summary, sharp findings, "
    "actionable next steps. Do not speculate beyond what the inputs "
    "support."
)

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "1-2 sentence executive summary of the analysis.",
        },
        "findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete findings, one per item. 2-6 items.",
        },
        "next_steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Recommended follow-ups for the orchestrator.",
        },
        # Metacognition fields read by `StructuredOutputProtocol`.
        # Optional so existing demos still validate without them.
        "self_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": (
                "Self-rated probability that the analysis satisfies the goal."
            ),
        },
        "uncertain_about": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Free-text identifiers for the assumptions/sub-claims that "
                "bottlenecked your confidence."
            ),
        },
        "outside_my_capability": {
            "type": "boolean",
            "description": (
                "True iff the goal is outside what you can verify (missing "
                "tool, post-cutoff knowledge, subjective judgement)."
            ),
        },
    },
    "required": ["summary", "findings"],
}


def build_analyst_registry() -> ToolRegistry:
    """ToolRegistry seeded with web tools sub-agents may opt into.

    Shared across every persisted sub-agent in the session — they
    select via ``ToolSpec(name=...)`` in their stored spec.
    """
    registry = ToolRegistry()
    registry.register(Tool(web_search, name="web_search"))
    registry.register(Tool(web_fetch, name="web_fetch"))
    return registry


# Public alias — the registry is no longer analyst-specific.
build_session_registry = build_analyst_registry


def build_analyst_spec(*, goal: str) -> AgentSpec:
    """Build a serializable :class:`AgentSpec` for the analyst.

    *goal* is embedded in the spec's metadata for traceability; the
    orchestrator passes it as the run input separately.
    """
    cfg = get_default_config()
    return AgentSpec(
        name="analyst",
        system_prompt=_SYSTEM_PROMPT,
        output_schema=_OUTPUT_SCHEMA,
        tools=[
            ToolSpec(name="web_search", description="Search the web for fresh info."),
            ToolSpec(name="web_fetch", description="Fetch a URL's text content."),
        ],
        model=cfg.LLM_MODEL,
        constraints=[
            "Return at most 6 findings.",
            "If the goal is fully answerable from the provided context, do not call web tools.",
        ],
        metadata={"goal": goal},
    )


def build_analyst_factory() -> AgentFactory:
    """Construct an :class:`AgentFactory` wired to the analyst registry."""
    cfg = get_default_config()
    return AgentFactory(
        registry=build_analyst_registry(),
        default_model=cfg.LLM_MODEL,
        api_key=cfg.require_llm_key(),
    )
