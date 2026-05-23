"""Tests for ``JsonViewerComponent``."""

from __future__ import annotations

from orqest.ui import JsonViewerComponent, JsonViewerComponentData


def test_json_viewer_default_data_none() -> None:
    spec = JsonViewerComponent(data=JsonViewerComponentData())
    assert spec.component_type == "json_viewer"
    assert spec.data.data is None
    assert spec.data.expanded_paths == []


def test_json_viewer_carries_arbitrary_payload() -> None:
    payload = {
        "items": [{"id": 1}, {"id": 2}],
        "meta": {"count": 2},
    }
    spec = JsonViewerComponent(
        data=JsonViewerComponentData(
            data=payload,
            expanded_paths=["", "items.0"],
            title="Inspect",
        )
    )
    revived = JsonViewerComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.data == payload
    assert revived.data.expanded_paths == ["", "items.0"]
    assert revived.data.title == "Inspect"


def test_json_viewer_accepts_scalar_data() -> None:
    """``Any``-typed `data` accepts non-dict structures too."""
    spec = JsonViewerComponentData(data=42)
    assert spec.data == 42
