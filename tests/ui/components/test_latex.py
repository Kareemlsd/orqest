"""Tests for ``LatexComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import LatexComponent, LatexComponentData


def test_latex_component_default_display_true() -> None:
    spec = LatexComponent(data=LatexComponentData(content=r"E = mc^2"))
    assert spec.component_type == "latex"
    assert spec.data.display is True


def test_latex_round_trip_inline() -> None:
    spec = LatexComponent(
        data=LatexComponentData(content=r"\alpha + \beta", display=False)
    )
    revived = LatexComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.display is False
    assert revived.data.content == r"\alpha + \beta"


def test_latex_content_required() -> None:
    with pytest.raises(ValidationError):
        LatexComponentData()  # type: ignore[call-arg]
