"""``MarkdownComponent`` — GFM-flavoured prose with code blocks.

The frontend renders via ``react-markdown + remark-gfm`` and the
existing ``CodeBlock`` renderer; this component is the agent's
escape hatch for arbitrary formatted prose where typed primitives
(``TextComponent`` / ``TableComponent``) would be too rigid.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from orqest.ui.spec import UIComponentSpec


class MarkdownComponentData(BaseModel):
    content: str
    """GFM markdown — tables, code, links, images. Frontend uses
    react-markdown + remark-gfm + the existing CodeBlock renderer."""


class MarkdownComponent(UIComponentSpec[MarkdownComponentData]):
    component_type: Literal["markdown"] = "markdown"
    data: MarkdownComponentData
