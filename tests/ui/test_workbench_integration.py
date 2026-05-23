"""Tests for Workbench.ui_registry integration."""

from __future__ import annotations

import pytest

from orqest.ui import ChartComponent, ComponentRegistry, PlanComponent
from orqest.workbench import Workbench


class _MockMemory:
    async def store(self, *a, **kw):
        return "id"

    async def recall(self, *a, **kw):
        return []


def test_workbench_default_ui_registry_has_first_party():
    wb = Workbench(memory=_MockMemory())
    types = set(wb.ui_registry.list_types())
    assert {"plan", "chart", "table", "form", "takeover_dialog"} <= types


def test_workbench_explicit_registry_skips_auto_registration():
    custom = ComponentRegistry()
    custom.register(PlanComponent)
    wb = Workbench(memory=_MockMemory(), ui_registry=custom)
    assert wb.ui_registry is custom
    # Custom registry does NOT have chart pre-registered.
    assert "chart" not in wb.ui_registry


def test_workbench_auto_register_disabled_starts_empty():
    wb = Workbench(memory=_MockMemory(), auto_register_first_party_ui=False)
    assert len(wb.ui_registry) == 0


def test_workbench_consumer_can_register_custom_component():
    wb = Workbench(memory=_MockMemory())
    from typing import Literal

    from pydantic import BaseModel

    from orqest.ui import UIComponentSpec

    class _MoleculeData(BaseModel):
        smiles: str

    class MoleculeViewer(UIComponentSpec[_MoleculeData]):
        component_type: Literal["molecule_viewer"] = "molecule_viewer"
        data: _MoleculeData

    wb.ui_registry.register(MoleculeViewer)
    assert "molecule_viewer" in wb.ui_registry


@pytest.mark.asyncio
async def test_workbench_ui_registry_validate_payload_round_trip():
    wb = Workbench(memory=_MockMemory())
    payload = {
        "component_type": "chart",
        "component_id": "c1",
        "data": {
            "chart_kind": "line",
            "title": "Trend",
            "series": [],
        },
    }
    spec = wb.ui_registry.validate_payload("chart", payload)
    assert isinstance(spec, ChartComponent)
    assert spec.data.chart_kind == "line"
