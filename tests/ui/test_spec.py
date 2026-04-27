"""Tests for UIComponentSpec[T] + UIDeltaEvent."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from orqest.ui import (
    PlanComponent,
    PlanComponentData,
    UIComponentSpec,
    UIDeltaEvent,
)
from orqest.plan.execution_plan import PlanTask


def test_ui_component_spec_round_trip_via_json():
    original = PlanComponent(
        component_id="plan-1",
        data=PlanComponentData(
            tasks=[PlanTask(id="t1", title="Step 1")]
        ),
        metadata={"agent": "x"},
    )
    blob = original.model_dump_json()
    revived = PlanComponent.model_validate_json(blob)
    assert revived.component_type == "plan"
    assert revived.component_id == "plan-1"
    assert len(revived.data.tasks) == 1
    assert revived.metadata == {"agent": "x"}


def test_ui_component_spec_default_id_is_unique():
    a = PlanComponent(data=PlanComponentData())
    b = PlanComponent(data=PlanComponentData())
    assert a.component_id != b.component_id


def test_ui_component_spec_to_event_data_is_json_safe():
    spec = PlanComponent(data=PlanComponentData())
    payload = spec.to_event_data()
    # Must round-trip through json
    import json

    json.dumps(payload)


def test_ui_delta_event_replace_op():
    delta = UIDeltaEvent(
        component_id="plan",
        component_type="plan",
        op="replace",
        path="tasks.0.status",
        value="completed",
    )
    assert delta.op == "replace"
    assert delta.path == "tasks.0.status"
    assert delta.value == "completed"


def test_ui_delta_event_default_path_is_root():
    delta = UIDeltaEvent(
        component_id="x", component_type="t", op="replace", value={"a": 1}
    )
    assert delta.path == ""


def test_ui_delta_event_round_trip():
    delta = UIDeltaEvent(
        component_id="x",
        component_type="chart",
        op="append",
        path="series.0.points",
        value={"x": 1, "y": 2},
    )
    blob = delta.model_dump_json()
    revived = UIDeltaEvent.model_validate_json(blob)
    assert revived == delta


def test_ui_delta_event_invalid_op_rejected():
    with pytest.raises(Exception):
        UIDeltaEvent(
            component_id="x",
            component_type="t",
            op="not-a-valid-op",  # type: ignore[arg-type]
        )


def test_subclass_must_set_component_type():
    """Concrete components inherit but their component_type Literal default
    differentiates them — different subclasses serialize with different
    discriminator values."""

    class _CustomData(BaseModel):
        x: int = 0

    from typing import Literal

    class CustomComponent(UIComponentSpec[_CustomData]):
        component_type: Literal["custom_x"] = "custom_x"
        data: _CustomData

    spec = CustomComponent(data=_CustomData(x=1))
    assert spec.component_type == "custom_x"
    assert spec.to_event_data()["component_type"] == "custom_x"
