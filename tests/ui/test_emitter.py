"""Tests for UIEmitter."""

from __future__ import annotations

import pytest

from orqest.observability.events import AgentEvent, EventBus
from orqest.ui import (
    ChartComponent,
    ChartComponentData,
    ChartSeries,
    PlanComponent,
    PlanComponentData,
    UIEmitter,
)


@pytest.mark.asyncio
async def test_emitter_init_publishes_typed_event():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("ui.plan.init", lambda e: captured.append(e))

    emitter = UIEmitter(bus)
    spec = PlanComponent(
        component_id="plan-x",
        data=PlanComponentData(tasks=[]),
    )
    event = await emitter.init(spec)
    assert event is not None
    assert len(captured) == 1
    assert captured[0].event_type == "ui.plan.init"
    assert captured[0].data["component_id"] == "plan-x"


@pytest.mark.asyncio
async def test_emitter_init_no_bus_returns_event_does_not_emit():
    emitter = UIEmitter(bus=None)
    spec = PlanComponent(data=PlanComponentData())
    event = await emitter.init(spec)
    assert event is not None
    assert event.event_type == "ui.plan.init"


@pytest.mark.asyncio
async def test_emitter_delta_publishes_typed_event():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("ui.plan.delta", lambda e: captured.append(e))

    emitter = UIEmitter(bus)
    await emitter.delta(
        component_id="plan-x",
        component_type="plan",
        op="replace",
        path="tasks.0.status",
        value="completed",
    )
    assert len(captured) == 1
    delta_data = captured[0].data
    assert delta_data["op"] == "replace"
    assert delta_data["path"] == "tasks.0.status"
    assert delta_data["value"] == "completed"


@pytest.mark.asyncio
async def test_emitter_remove_publishes_typed_event():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("ui.chart.remove", lambda e: captured.append(e))

    emitter = UIEmitter(bus)
    await emitter.remove(component_id="chart-1", component_type="chart")
    assert len(captured) == 1
    assert captured[0].data == {"component_id": "chart-1"}


@pytest.mark.asyncio
async def test_emitter_chart_init_carries_typed_data():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("ui.chart.init", lambda e: captured.append(e))

    emitter = UIEmitter(bus)
    spec = ChartComponent(
        component_id="c1",
        data=ChartComponentData(
            chart_kind="bar",
            title="Sales",
            series=[ChartSeries(name="2024", points=[{"x": 1, "y": 2}])],
        ),
    )
    await emitter.init(spec)
    assert len(captured) == 1
    assert captured[0].data["data"]["chart_kind"] == "bar"
    assert captured[0].data["data"]["series"][0]["name"] == "2024"


@pytest.mark.asyncio
async def test_emitter_agent_name_override():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("ui.plan.init", lambda e: captured.append(e))

    emitter = UIEmitter(bus, agent_name="default_agent")
    spec = PlanComponent(data=PlanComponentData())
    await emitter.init(spec, agent_name="override_agent")
    assert captured[0].agent_name == "override_agent"


@pytest.mark.asyncio
async def test_emitter_event_type_formatters():
    """ui_init/delta/remove_event_type produce the documented strings."""
    from orqest.ui import (
        ui_delta_event_type,
        ui_init_event_type,
        ui_remove_event_type,
    )

    assert ui_init_event_type("plan") == "ui.plan.init"
    assert ui_delta_event_type("chart") == "ui.chart.delta"
    assert ui_remove_event_type("table") == "ui.table.remove"
