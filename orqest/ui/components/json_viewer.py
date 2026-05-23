"""``JsonViewerComponent`` — interactive collapsible JSON tree."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec


class JsonViewerComponentData(BaseModel):
    data: Any = None
    """Any JSON-serialisable structure (object, array, scalar)."""
    expanded_paths: list[str] = Field(default_factory=list)
    """Paths to expand by default (e.g. ``["", "items.0"]``)."""
    title: str = ""


class JsonViewerComponent(UIComponentSpec[JsonViewerComponentData]):
    component_type: Literal["json_viewer"] = "json_viewer"
    data: JsonViewerComponentData
