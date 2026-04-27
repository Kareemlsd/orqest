"""``LatexComponent`` — KaTeX-rendered math expression."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from orqest.ui.spec import UIComponentSpec


class LatexComponentData(BaseModel):
    content: str
    """LaTeX source rendered via KaTeX. Use ``display=True`` for block
    math, ``False`` for inline."""
    display: bool = True


class LatexComponent(UIComponentSpec[LatexComponentData]):
    component_type: Literal["latex"] = "latex"
    data: LatexComponentData
