"""Tests for first-party UIComponent shapes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import (
    ChartComponent,
    ChartComponentData,
    ChartSeries,
    FormComponent,
    FormComponentData,
    FormField,
    PlanComponent,
    PlanComponentData,
    TableColumn,
    TableComponent,
    TableComponentData,
    TakeoverDialogComponent,
    TakeoverDialogData,
)
from orqest.plan.execution_plan import PlanTask


# ---- PlanComponent ----------------------------------------------------


def test_plan_component_default():
    spec = PlanComponent(data=PlanComponentData())
    assert spec.component_type == "plan"
    assert spec.data.tasks == []


def test_plan_component_carries_plan_tasks():
    spec = PlanComponent(
        data=PlanComponentData(
            tasks=[PlanTask(id="t1", title="step")],
        )
    )
    assert spec.data.tasks[0].id == "t1"


# ---- ChartComponent ---------------------------------------------------


def test_chart_component_data_required():
    spec = ChartComponent(
        data=ChartComponentData(chart_kind="line", title="Trend")
    )
    assert spec.component_type == "chart"
    assert spec.data.chart_kind == "line"


def test_chart_kind_literal_enforced():
    with pytest.raises(ValidationError):
        ChartComponentData(chart_kind="3d-rotational")  # type: ignore[arg-type]


def test_chart_series_default_points_empty():
    s = ChartSeries(name="x")
    assert s.points == []


def test_chart_round_trip():
    original = ChartComponent(
        data=ChartComponentData(
            chart_kind="bar",
            title="Sales",
            series=[ChartSeries(name="q1", points=[{"x": 1, "y": 2}])],
        )
    )
    blob = original.model_dump_json()
    revived = ChartComponent.model_validate_json(blob)
    assert revived.data.title == "Sales"
    assert revived.data.series[0].points[0]["x"] == 1


# ---- TableComponent ---------------------------------------------------


def test_table_component_columns_required():
    with pytest.raises(ValidationError):
        TableComponentData()  # type: ignore[call-arg]


def test_table_component_with_rows():
    spec = TableComponent(
        data=TableComponentData(
            columns=[TableColumn(key="id", label="ID", kind="number")],
            rows=[{"id": 1}, {"id": 2}],
        )
    )
    assert spec.component_type == "table"
    assert len(spec.data.rows) == 2


def test_table_column_kind_literal_enforced():
    with pytest.raises(ValidationError):
        TableColumn(key="x", label="X", kind="bool")  # type: ignore[arg-type]


# ---- FormComponent ----------------------------------------------------


def test_form_component_with_fields():
    spec = FormComponent(
        data=FormComponentData(
            title="Sign in",
            fields=[
                FormField(key="email", label="Email", required=True),
                FormField(
                    key="role",
                    label="Role",
                    kind="select",
                    options=["admin", "user"],
                ),
            ],
        )
    )
    assert spec.component_type == "form"
    assert spec.data.fields[1].kind == "select"


def test_form_field_kind_literal_enforced():
    with pytest.raises(ValidationError):
        FormField(key="x", label="X", kind="exotic")  # type: ignore[arg-type]


def test_form_default_submit_event():
    data = FormComponentData()
    assert data.submit_event == "form.submitted"


# ---- TakeoverDialogComponent -----------------------------------------


def test_takeover_dialog_default_kind_confirm():
    data = TakeoverDialogData()
    assert data.kind == "confirm"


def test_takeover_dialog_choice_kind_with_options():
    spec = TakeoverDialogComponent(
        data=TakeoverDialogData(
            kind="choice",
            title="Pick one",
            choices=["A", "B", "C"],
        )
    )
    assert spec.component_type == "takeover_dialog"
    assert spec.data.choices == ["A", "B", "C"]


def test_takeover_dialog_kind_literal_enforced():
    with pytest.raises(ValidationError):
        TakeoverDialogData(kind="surprise")  # type: ignore[arg-type]
