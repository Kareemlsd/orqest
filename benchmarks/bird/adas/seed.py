"""Seed topology — the trivial single-agent baseline ADAS evolves from.

Per the locked decision (`.claude/plans/ORQEST_VALIDATION_DECISIONS_2026-05-15.md`
#5), the meta-agent starts from scratch with a single ``sql_generator``
agent. Anything ADAS adds (schema linking, parallel voting, refinement
loops, routers) is a real discovered improvement.
"""
from __future__ import annotations

from orqest.orchestration.spec import (
    AgentStepSpec,
    PipelineSpec,
    PipelineStepEntry,
)


def seed_topology() -> PipelineSpec:
    """Seed: 3-step Pipeline (schema_linker → sql_generator → terminal_finalizer).

    Slightly richer than a single generator so the meta-agent's simplest
    mutation (insert/reorder/swap one step) lands a valid topology rather
    than having to invent a Router or RefinementLoop scaffold. The cost
    of one extra LLM call vs the trivial seed is worth it for search
    convergence speed.
    """
    return PipelineSpec(
        name="seed_pipeline",
        steps=[
            PipelineStepEntry(
                operation=AgentStepSpec(agent_name="schema_linker")
            ),
            PipelineStepEntry(
                operation=AgentStepSpec(agent_name="sql_generator")
            ),
            PipelineStepEntry(
                operation=AgentStepSpec(agent_name="terminal_finalizer")
            ),
        ],
    )


__all__ = ["seed_topology"]
