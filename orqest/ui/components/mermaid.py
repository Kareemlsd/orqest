"""``MermaidComponent`` — Mermaid-grammar diagrams (flow / sequence / ER / gantt / …)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from orqest.ui.spec import UIComponentSpec


class MermaidComponentData(BaseModel):
    diagram: str
    """Mermaid source. flowchart / sequence / classDiagram / erDiagram /
    gantt / mindmap / etc."""
    title: str = ""


class MermaidComponent(UIComponentSpec[MermaidComponentData]):
    component_type: Literal["mermaid"] = "mermaid"
    data: MermaidComponentData
