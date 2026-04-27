"""``LayoutComponent`` — recursive container for arbitrary child components.

The cornerstone of generative UI's compositional layer: an agent
arranges other registered components inside a Layout to build arbitrary
interfaces (dashboards, side-by-side comparisons, vertical stacks).
Layouts can nest Layouts, so the agent can express any tree it wants.

The ``children`` field is intentionally typed as ``list[dict[str, Any]]``
rather than ``list[UIComponentSpec]``: keeping it as raw dicts avoids
the need to materialise a closed discriminated union of every
registered component type at import time. Third-party components
register themselves on the per-Workbench :class:`ComponentRegistry`
without needing to extend a static union, and the dicts round-trip
cleanly through the SSE channel — the frontend resolves each child by
its ``component_type`` discriminator just like the top-level component.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec

LayoutDirection = Literal["vertical", "horizontal", "grid"]
LayoutAlign = Literal["start", "center", "end", "stretch"]


class LayoutComponentData(BaseModel):
    direction: LayoutDirection = "vertical"
    gap: int = 8
    """Tailwind spacing unit. ``8`` ≈ 0.5rem (matches existing Polymath UI)."""
    align: LayoutAlign = "stretch"
    grid_columns: int | None = None
    """Number of columns for ``direction="grid"`` (ignored otherwise)."""
    children: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of UIComponentSpec dicts. Each child must have a "
            "registered component_type. Recursive — Layouts can nest "
            "Layouts to arbitrary depth."
        ),
    )


class LayoutComponent(UIComponentSpec[LayoutComponentData]):
    component_type: Literal["layout"] = "layout"
    data: LayoutComponentData
