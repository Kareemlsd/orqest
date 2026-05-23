"""``TakeoverDialogComponent`` — modal asking the user to take control.

Generalises the takeover-button pattern from Polymath: when the agent
hits a capability boundary or the watchdog escalates, emit one of these
to surface the question to the user.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec

TakeoverKind = Literal["confirm", "input", "choice"]


class TakeoverDialogData(BaseModel):
    kind: TakeoverKind = "confirm"
    title: str = "Action needed"
    message: str = ""
    choices: list[str] = Field(default_factory=list)
    """For ``choice`` kind — the offered options."""
    confirm_label: str = "Continue"
    cancel_label: str = "Cancel"
    response_event: str = "takeover.responded"


class TakeoverDialogComponent(UIComponentSpec[TakeoverDialogData]):
    component_type: Literal["takeover_dialog"] = "takeover_dialog"
    data: TakeoverDialogData
