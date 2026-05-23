"""Tests for ``LayoutComponent`` — the recursive container."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import LayoutComponent, LayoutComponentData


def test_layout_component_default_direction() -> None:
    spec = LayoutComponent(data=LayoutComponentData())
    assert spec.component_type == "layout"
    assert spec.data.direction == "vertical"
    assert spec.data.gap == 8
    assert spec.data.align == "stretch"
    assert spec.data.children == []


def test_layout_direction_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        LayoutComponentData(direction="diagonal")  # type: ignore[arg-type]


def test_layout_align_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        LayoutComponentData(align="middle")  # type: ignore[arg-type]


def test_layout_round_trip_with_nested_children() -> None:
    """Nested layout dicts round-trip through the JSON channel."""
    inner = {
        "component_type": "text",
        "component_id": "t1",
        "data": {"content": "Hello"},
        "metadata": {},
    }
    outer = LayoutComponent(
        data=LayoutComponentData(
            direction="horizontal",
            gap=4,
            children=[inner],
        )
    )
    blob = outer.model_dump_json()
    revived = LayoutComponent.model_validate_json(blob)
    assert revived.data.direction == "horizontal"
    assert revived.data.gap == 4
    assert revived.data.children[0]["component_type"] == "text"
    assert revived.data.children[0]["data"]["content"] == "Hello"


def test_layout_grid_columns_optional() -> None:
    spec = LayoutComponent(
        data=LayoutComponentData(direction="grid", grid_columns=3)
    )
    assert spec.data.grid_columns == 3
