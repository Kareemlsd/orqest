"""``ChartComponent`` — typed chart spec.

Supports a small set of chart kinds covering the common cases
(line/bar/scatter/pie/heatmap). The frontend renderer reads ``series``
directly — no separate fetch required.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec

ChartKind = Literal["line", "bar", "scatter", "pie", "heatmap"]


class ChartSeries(BaseModel):
    """One labelled data series. Points are dicts so the renderer can
    pick out the relevant axes (e.g. ``{"x": ..., "y": ...}``)."""

    name: str
    points: list[dict[str, Any]] = Field(default_factory=list)


class ChartComponentData(BaseModel):
    chart_kind: ChartKind = "line"
    title: str = ""
    x_axis: str | None = None
    y_axis: str | None = None
    series: list[ChartSeries] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    """Free-form renderer-specific knobs (axis formatters, colour
    scheme, etc.). Not load-bearing for the protocol."""


class ChartComponent(UIComponentSpec[ChartComponentData]):
    component_type: Literal["chart"] = "chart"
    data: ChartComponentData
