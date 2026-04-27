"""Tests for ``TextComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import TextComponent, TextComponentData


def test_text_component_default_variant() -> None:
    spec = TextComponent(data=TextComponentData(content="hello"))
    assert spec.component_type == "text"
    assert spec.data.variant == "body"
    assert spec.data.tone == "default"


def test_text_component_round_trip() -> None:
    spec = TextComponent(
        data=TextComponentData(
            content="Welcome", variant="heading", tone="accent"
        )
    )
    revived = TextComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.content == "Welcome"
    assert revived.data.variant == "heading"
    assert revived.data.tone == "accent"


def test_text_variant_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        TextComponentData(content="x", variant="title")  # type: ignore[arg-type]


def test_text_tone_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        TextComponentData(content="x", tone="rainbow")  # type: ignore[arg-type]
