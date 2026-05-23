"""``ButtonComponent`` — interactive trigger that posts back to the agent."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec

ButtonVariant = Literal["primary", "secondary", "ghost", "destructive"]


class ButtonComponentData(BaseModel):
    label: str
    event_name: str = "ui.button.clicked"
    """The event_type the frontend POSTs back when the button is
    clicked. The agent subscribes to this via the SSE bus + event-loop
    integration."""
    event_payload: dict[str, Any] = Field(default_factory=dict)
    variant: ButtonVariant = "primary"
    icon: str | None = None
    disabled: bool = False


class ButtonComponent(UIComponentSpec[ButtonComponentData]):
    component_type: Literal["button"] = "button"
    data: ButtonComponentData
