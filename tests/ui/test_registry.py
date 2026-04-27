"""Tests for ComponentRegistry."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel

from orqest.ui import (
    ChartComponent,
    ComponentRegistry,
    PlanComponent,
    UIComponentSpec,
    default_registry,
)


def test_register_concrete_component():
    reg = ComponentRegistry()
    reg.register(PlanComponent)
    assert reg.get("plan") is PlanComponent
    assert "plan" in reg
    assert len(reg) == 1


def test_register_warns_on_duplicate_without_overwrite(caplog):
    reg = ComponentRegistry()
    reg.register(PlanComponent)
    reg.register(PlanComponent)  # second register — no-op (logs WARN)
    assert reg.get("plan") is PlanComponent
    assert len(reg) == 1


def test_register_overwrite_replaces():
    class _OtherData(BaseModel):
        x: int = 0

    class _OtherPlan(UIComponentSpec[_OtherData]):
        component_type: Literal["plan"] = "plan"
        data: _OtherData

    reg = ComponentRegistry()
    reg.register(PlanComponent)
    reg.register(_OtherPlan, overwrite=True)
    assert reg.get("plan") is _OtherPlan


def test_get_returns_none_for_unknown():
    assert ComponentRegistry().get("nonexistent") is None


def test_validate_payload_returns_typed_spec():
    reg = ComponentRegistry()
    reg.register(PlanComponent)
    payload = {
        "component_type": "plan",
        "component_id": "test",
        "data": {"tasks": []},
    }
    result = reg.validate_payload("plan", payload)
    assert isinstance(result, PlanComponent)
    assert result.component_id == "test"


def test_validate_payload_unknown_type_returns_none():
    reg = ComponentRegistry()
    assert reg.validate_payload("nonexistent", {}) is None


def test_validate_payload_invalid_data_returns_none():
    reg = ComponentRegistry()
    reg.register(PlanComponent)
    # Missing required `data` field for the component.
    result = reg.validate_payload("plan", {"component_type": "plan"})
    assert result is None


def test_list_types_returns_sorted():
    reg = ComponentRegistry()
    reg.register(PlanComponent)
    reg.register(ChartComponent)
    assert reg.list_types() == ["chart", "plan"]


def test_default_registry_has_first_party_components():
    reg = default_registry()
    types = set(reg.list_types())
    assert {"plan", "chart", "table", "form", "takeover_dialog"} <= types


def test_default_registry_has_layer_one_compositional_primitives():
    """Layer 1: compositional primitives must register unconditionally."""
    reg = default_registry()
    types = set(reg.list_types())
    layer_one = {
        "layout",
        "text",
        "markdown",
        "image",
        "badge",
        "button",
        "input",
    }
    assert layer_one <= types


def test_default_registry_has_layer_two_grammar_components():
    """Layer 2: declarative grammars register unconditionally."""
    reg = default_registry()
    types = set(reg.list_types())
    layer_two = {"vega_chart", "mermaid", "latex", "json_viewer"}
    assert layer_two <= types


def test_default_registry_has_layer_three_sandboxed_html():
    """Layer 3 also registers in core; consumers gate emission/rendering."""
    reg = default_registry()
    assert "sandboxed_html" in reg


def test_default_registry_count_matches_first_party_set():
    """Sanity: default_registry size is the union of all three layers."""
    reg = default_registry()
    # 5 existing + 7 (Layer 1) + 4 (Layer 2) + 1 (Layer 3) = 17.
    assert len(reg) == 17


def test_registry_extract_type_rejects_non_str_default():
    """Subclass without a Literal default → register raises."""

    class _BadData(BaseModel):
        x: int = 0

    class BadSpec(UIComponentSpec[_BadData]):
        # No Literal override — inherits the str default from the base.
        # The base's component_type field has no default value,
        # so model_fields[...].default is PydanticUndefined.
        data: _BadData = _BadData()

    reg = ComponentRegistry()
    with pytest.raises(ValueError):
        reg.register(BadSpec)
