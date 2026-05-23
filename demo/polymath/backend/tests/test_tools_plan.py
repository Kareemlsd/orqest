"""Tests for polymath.tools.plan.

Verifies that ``init_plan`` constructs the :class:`ExecutionPlan`,
mounts it on :class:`PolymathState`, and dual-emits both the legacy
``plan.init`` and the typed ``ui.plan.init`` event after the
Phase β consolidation (see
``.claude/POLYMATH_ASSESSMENT_2026-04-25.md`` §7 item 3).
"""

from __future__ import annotations

import json
import types
from typing import Any
from uuid import uuid4

import pytest

from polymath import runtime as runtime_mod
from polymath.state import PolymathState
from polymath.tools.plan import _init_plan, _SubtaskIn, _TaskIn, _update_plan


def _ctx(sid: str) -> Any:
    return types.SimpleNamespace(deps=PolymathState(session_id=sid))


@pytest.mark.asyncio
async def test_init_plan_emits_dual_events() -> None:
    """``init_plan`` fires both legacy and typed UI events."""
    sid = str(uuid4())
    rt = runtime_mod.get_runtime(sid)
    seen: list[tuple[str, dict]] = []

    async def handler(evt) -> None:
        seen.append((evt.event_type, evt.data))

    rt.workbench.event_bus.subscribe_all(handler)

    await _init_plan(
        _ctx(sid),
        tasks=[
            _TaskIn(
                id="t1",
                title="Research",
                subtasks=[
                    _SubtaskIn(id="s1", title="Search the web", tools=["web_search"]),
                ],
            ),
            _TaskIn(id="t2", title="Synthesize"),
        ],
    )

    types_emitted = [t for t, _ in seen]
    assert "plan.init" in types_emitted
    assert "ui.plan.init" in types_emitted

    # Legacy event payload — frontend's PlanHeader still consumes this.
    legacy = next(d for t, d in seen if t == "plan.init")
    assert [t["id"] for t in legacy["tasks"]] == ["t1", "t2"]

    # Typed UI envelope — generative-UI channel.
    typed = next(d for t, d in seen if t == "ui.plan.init")
    assert typed["component_type"] == "plan"
    assert typed["component_id"] == "plan"
    assert [t["id"] for t in typed["data"]["tasks"]] == ["t1", "t2"]


@pytest.mark.asyncio
async def test_init_plan_populates_state() -> None:
    """The constructed ``ExecutionPlan`` lands on ``PolymathState.plan``."""
    sid = str(uuid4())
    ctx = _ctx(sid)
    result = json.loads(
        await _init_plan(
            ctx,
            tasks=[_TaskIn(id="only", title="Solo")],
        )
    )
    assert result == {"tasks": ["only"]}
    assert ctx.deps.plan is not None
    assert [t.id for t in ctx.deps.plan.tasks] == ["only"]


@pytest.mark.asyncio
async def test_update_plan_emits_dual_delta() -> None:
    """``update_plan`` after ``init_plan`` fires legacy + typed delta."""
    sid = str(uuid4())
    rt = runtime_mod.get_runtime(sid)
    ctx = _ctx(sid)

    await _init_plan(
        ctx,
        tasks=[_TaskIn(id="t1", title="First")],
    )

    seen: list[tuple[str, dict]] = []

    async def handler(evt) -> None:
        seen.append((evt.event_type, evt.data))

    rt.workbench.event_bus.subscribe_all(handler)

    await _update_plan(ctx, task_id="t1", status="completed")

    types_emitted = [t for t, _ in seen]
    assert "plan.task.updated" in types_emitted
    # Phase β: dual-emission. ``ui.plan.delta`` rides alongside the
    # legacy event so the generative-UI channel sees the same change.
    assert "ui.plan.delta" in types_emitted
