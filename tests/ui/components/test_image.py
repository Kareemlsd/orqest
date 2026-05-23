"""Tests for ``ImageComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import ImageComponent, ImageComponentData


def test_image_component_minimum_url_only() -> None:
    spec = ImageComponent(
        data=ImageComponentData(url="https://example.com/img.png")
    )
    assert spec.component_type == "image"
    assert spec.data.alt == ""
    assert spec.data.caption == ""
    assert spec.data.max_height_px is None
    assert spec.data.max_width_px is None


def test_image_component_round_trip_with_caption() -> None:
    spec = ImageComponent(
        data=ImageComponentData(
            url="https://example.com/img.png",
            alt="alt text",
            caption="A pretty picture",
            max_height_px=300,
        )
    )
    revived = ImageComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.url == "https://example.com/img.png"
    assert revived.data.alt == "alt text"
    assert revived.data.caption == "A pretty picture"
    assert revived.data.max_height_px == 300


def test_image_url_required() -> None:
    with pytest.raises(ValidationError):
        ImageComponentData()  # type: ignore[call-arg]
