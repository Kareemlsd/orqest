"""``VegaChartComponent`` — Vega-Lite chart spec passed straight to the renderer.

Where :class:`ChartComponent` exposes a small set of chart kinds with
pre-shaped series, ``VegaChartComponent`` lets the agent emit a full
Vega-Lite spec for anything more sophisticated — geographic, layered,
faceted, multi-encoding. The backend treats the spec as opaque; the
frontend hands it to ``vega-embed``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec


class VegaChartComponentData(BaseModel):
    spec: dict[str, Any] = Field(default_factory=dict)
    """Full Vega-Lite spec (https://vega.github.io/vega-lite/). The
    frontend imports vega-embed and renders. The agent emits the JSON
    directly — Vega-Lite syntax is well-documented and the LLM is
    typically familiar with it."""


class VegaChartComponent(UIComponentSpec[VegaChartComponentData]):
    component_type: Literal["vega_chart"] = "vega_chart"
    data: VegaChartComponentData
