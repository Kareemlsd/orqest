"""``BadgeComponent`` — short status chip with tone + optional icon."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from orqest.ui.spec import UIComponentSpec

BadgeTone = Literal[
    "default", "accent", "success", "warning", "destructive", "info"
]


class BadgeComponentData(BaseModel):
    label: str
    tone: BadgeTone = "default"
    icon: str | None = None
    """``lucide-react`` icon name. The frontend resolves the symbol; if
    the icon is unknown it falls back to label-only."""


class BadgeComponent(UIComponentSpec[BadgeComponentData]):
    component_type: Literal["badge"] = "badge"
    data: BadgeComponentData
