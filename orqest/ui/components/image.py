"""``ImageComponent`` — typed image / figure with optional caption."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from orqest.ui.spec import UIComponentSpec


class ImageComponentData(BaseModel):
    url: str
    alt: str = ""
    caption: str = ""
    max_height_px: int | None = None
    max_width_px: int | None = None


class ImageComponent(UIComponentSpec[ImageComponentData]):
    component_type: Literal["image"] = "image"
    data: ImageComponentData
