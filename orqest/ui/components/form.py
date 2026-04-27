"""``FormComponent`` — typed input form for user submissions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec

FieldKind = Literal[
    "text", "textarea", "number", "checkbox", "select", "multiselect", "date"
]


class FormField(BaseModel):
    key: str
    label: str
    kind: FieldKind = "text"
    required: bool = False
    placeholder: str = ""
    options: list[str] = Field(default_factory=list)
    """For ``select`` / ``multiselect`` — the available choices."""
    default: Any = None


class FormComponentData(BaseModel):
    title: str = ""
    description: str = ""
    fields: list[FormField] = Field(default_factory=list)
    submit_label: str = "Submit"
    submit_event: str = "form.submitted"
    """The event_type the frontend should emit (back to the agent) on
    submission. Decoupled from the component_type so multiple forms can
    share a single rendering path."""


class FormComponent(UIComponentSpec[FormComponentData]):
    component_type: Literal["form"] = "form"
    data: FormComponentData
