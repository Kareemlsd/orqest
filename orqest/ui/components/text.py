"""``TextComponent`` — typed inline / block text primitive."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from orqest.ui.spec import UIComponentSpec

TextVariant = Literal["heading", "subheading", "body", "caption", "code-inline"]
TextTone = Literal["default", "muted", "accent", "destructive"]


class TextComponentData(BaseModel):
    content: str
    variant: TextVariant = "body"
    tone: TextTone = "default"


class TextComponent(UIComponentSpec[TextComponentData]):
    component_type: Literal["text"] = "text"
    data: TextComponentData
