"""``InputComponent`` — typed standalone input field (form-less)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec

InputKind = Literal[
    "text", "textarea", "number", "file", "slider", "date", "checkbox"
]


class InputComponentData(BaseModel):
    kind: InputKind = "text"
    name: str
    label: str = ""
    default: Any = None
    placeholder: str = ""
    event_name: str = "ui.input.changed"
    event_payload: dict[str, Any] = Field(default_factory=dict)
    # Kind-specific knobs:
    min: float | None = None
    max: float | None = None
    step: float | None = None
    rows: int | None = None
    """Textarea row count (ignored for other kinds)."""
    accept: str | None = None
    """File mime/extension filter (e.g. ``"image/*"`` or ``".csv,.tsv"``)."""


class InputComponent(UIComponentSpec[InputComponentData]):
    component_type: Literal["input"] = "input"
    data: InputComponentData
