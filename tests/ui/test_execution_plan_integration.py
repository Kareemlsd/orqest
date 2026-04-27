"""Tests for ExecutionPlan dual-emission + as_component integration."""

from __future__ import annotations

import pytest

from orqest.observability.events import AgentEvent, EventBus
from orqest.plan import ExecutionPlan, PlanTask
from orqest.ui import PlanComponent


# ---- as_component ----------------------------------------------------


def test_as_component_wraps_plan_tasks():
    plan = ExecutionPlan(
        tasks=[
            PlanTask(id="t1", title="Step 1"),
            PlanTask(id="t2", title="Step 2"),
        ]
    )
    component = plan.as_component()
    assert isinstance(component, PlanComponent)
    assert component.component_type == "plan"
    assert component.component_id == "plan"  # default
    assert len(component.data.tasks) == 2
    assert component.data.tasks[0].id == "t1"


def test_as_component_custom_id():
    plan = ExecutionPlan(tasks=[]).enable_ui_events(component_id="my-plan")
    component = plan.as_component()
    assert component.component_id == "my-plan"


# ---- Backward-compat: flag off (default) -----------------------------


@pytest.mark.asyncio
async def test_emit_init_flag_off_emits_only_legacy():
    """With flag off, emit_init produces exactly one plan.init event."""
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe_all(lambda e: captured.append(e))

    plan = ExecutionPlan(tasks=[PlanTask(id="t1", title="Step")])
    await plan.emit_init(bus)

    assert len(captured) == 1
    assert captured[0].event_type == "plan.init"


@pytest.mark.asyncio
async def test_set_task_status_flag_off_emits_only_legacy():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe_all(lambda e: captured.append(e))

    plan = ExecutionPlan(tasks=[PlanTask(id="t1", title="Step")])
    await plan.set_task_status("t1", "completed", bus=bus)

    assert len(captured) == 1
    assert captured[0].event_type == "plan.task.updated"


# ---- Flag on: dual emission ------------------------------------------


@pytest.mark.asyncio
async def test_emit_init_flag_on_dual_emits():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe_all(lambda e: captured.append(e))

    plan = ExecutionPlan(
        tasks=[PlanTask(id="t1", title="Step")]
    ).enable_ui_events()
    await plan.emit_init(bus)

    assert len(captured) == 2
    types = {e.event_type for e in captured}
    assert types == {"plan.init", "ui.plan.init"}


@pytest.mark.asyncio
async def test_set_task_status_flag_on_dual_emits():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe_all(lambda e: captured.append(e))

    plan = ExecutionPlan(
        tasks=[PlanTask(id="t1", title="Step")]
    ).enable_ui_events()
    await plan.set_task_status("t1", "completed", bus=bus)

    types = [e.event_type for e in captured]
    assert "plan.task.updated" in types
    assert "ui.plan.delta" in types


@pytest.mark.asyncio
async def test_set_task_status_ui_delta_path_for_top_level_task():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("ui.plan.delta", lambda e: captured.append(e))

    plan = ExecutionPlan(
        tasks=[
            PlanTask(id="a", title="A"),
            PlanTask(id="b", title="B"),
        ]
    ).enable_ui_events()
    await plan.set_task_status("b", "completed", bus=bus)

    delta = captured[0].data
    assert delta["op"] == "replace"
    assert delta["path"] == "tasks.1.status"
    assert delta["value"] == "completed"


@pytest.mark.asyncio
async def test_set_task_status_ui_delta_path_for_subtask():
    from orqest.plan import PlanSubtask

    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("ui.plan.delta", lambda e: captured.append(e))

    plan = ExecutionPlan(
        tasks=[
            PlanTask(
                id="t1",
                title="Step 1",
                subtasks=[
                    PlanSubtask(id="s1", title="sub 1"),
                    PlanSubtask(id="s2", title="sub 2"),
                ],
            ),
        ]
    ).enable_ui_events()
    await plan.set_task_status("t1", "in-progress", subtask_id="s2", bus=bus)

    delta = captured[0].data
    assert delta["path"] == "tasks.0.subtasks.1.status"


@pytest.mark.asyncio
async def test_enable_ui_events_returns_self_for_chaining():
    plan = ExecutionPlan(tasks=[])
    result = plan.enable_ui_events()
    assert result is plan
    assert plan._emit_ui_events is True
