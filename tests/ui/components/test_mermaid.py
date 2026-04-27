"""Tests for ``MermaidComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import MermaidComponent, MermaidComponentData


def test_mermaid_component_carries_source() -> None:
    src = "graph TD\n  A --> B\n  B --> C"
    spec = MermaidComponent(data=MermaidComponentData(diagram=src))
    assert spec.component_type == "mermaid"
    assert spec.data.diagram == src
    assert spec.data.title == ""


def test_mermaid_round_trip_with_title() -> None:
    spec = MermaidComponent(
        data=MermaidComponentData(diagram="sequenceDiagram\n  A->>B: hi", title="seq")
    )
    revived = MermaidComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.title == "seq"
    assert "sequenceDiagram" in revived.data.diagram


def test_mermaid_diagram_required() -> None:
    with pytest.raises(ValidationError):
        MermaidComponentData()  # type: ignore[call-arg]
