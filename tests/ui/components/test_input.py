"""Tests for ``InputComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import InputComponent, InputComponentData


def test_input_component_default_kind() -> None:
    spec = InputComponent(data=InputComponentData(name="username"))
    assert spec.component_type == "input"
    assert spec.data.kind == "text"
    assert spec.data.event_name == "ui.input.changed"


def test_input_component_round_trip_slider() -> None:
    spec = InputComponent(
        data=InputComponentData(
            kind="slider",
            name="volume",
            label="Volume",
            default=50,
            min=0,
            max=100,
            step=1,
        )
    )
    revived = InputComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.kind == "slider"
    assert revived.data.min == 0
    assert revived.data.max == 100
    assert revived.data.step == 1


def test_input_kind_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        InputComponentData(name="x", kind="dropdown")  # type: ignore[arg-type]


def test_input_name_required() -> None:
    with pytest.raises(ValidationError):
        InputComponentData()  # type: ignore[call-arg]
