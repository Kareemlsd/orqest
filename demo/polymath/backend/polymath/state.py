"""Polymath per-session state.

Extends :class:`orqest.agents.BaseSessionState` (see
``docs/concepts/base_session_state.md``) with a live
:class:`~orqest.plan.ExecutionPlan`, a sandbox handle placeholder, and
an artifact index. Kept deliberately thin — Phase 0 only uses a subset.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from orqest.agents import BaseSessionState
from orqest.plan import ExecutionPlan


class PolymathState(BaseSessionState):
    """Session state for one chat session.

    Attributes:
        plan: Live execution plan, mutated in place by plan.* tools.
        sandbox_id: Docker container id once a sandbox is attached (Phase 2+).
        artifact_ids: Ordered list of artifact UUIDs produced this session.
        step_count: Tool-call counter; the agent loop bounds this to avoid
            runaway behavior (see plan's risk mitigation #5).
    """

    plan: ExecutionPlan = Field(default_factory=ExecutionPlan)
    sandbox_id: str | None = None
    artifact_ids: list[UUID] = Field(default_factory=list)
    step_count: int = 0
