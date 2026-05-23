"""Tests for ``VegaChartComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import VegaChartComponent, VegaChartComponentData


def test_vega_chart_component_default_spec_empty() -> None:
    spec = VegaChartComponent(data=VegaChartComponentData())
    assert spec.component_type == "vega_chart"
    assert spec.data.spec == {}


def test_vega_chart_round_trip_carries_opaque_spec() -> None:
    vl_spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "mark": "bar",
        "data": {"values": [{"a": "x", "b": 1}, {"a": "y", "b": 2}]},
        "encoding": {
            "x": {"field": "a", "type": "nominal"},
            "y": {"field": "b", "type": "quantitative"},
        },
    }
    spec = VegaChartComponent(data=VegaChartComponentData(spec=vl_spec))
    revived = VegaChartComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.spec["mark"] == "bar"
    assert revived.data.spec["data"]["values"][1]["b"] == 2


def test_vega_chart_spec_must_be_dict() -> None:
    with pytest.raises(ValidationError):
        VegaChartComponentData(spec="not-a-dict")  # type: ignore[arg-type]
