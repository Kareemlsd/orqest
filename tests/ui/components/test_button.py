"""Tests for ``ButtonComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import ButtonComponent, ButtonComponentData


def test_button_default_event_name_and_variant() -> None:
    spec = ButtonComponent(data=ButtonComponentData(label="Click me"))
    assert spec.component_type == "button"
    assert spec.data.event_name == "ui.button.clicked"
    assert spec.data.variant == "primary"
    assert spec.data.disabled is False
    assert spec.data.event_payload == {}


def test_button_round_trip_with_payload() -> None:
    spec = ButtonComponent(
        data=ButtonComponentData(
            label="Confirm",
            event_name="confirm.purchase",
            event_payload={"order_id": "abc-123"},
            variant="destructive",
            disabled=True,
        )
    )
    revived = ButtonComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.event_name == "confirm.purchase"
    assert revived.data.event_payload == {"order_id": "abc-123"}
    assert revived.data.variant == "destructive"
    assert revived.data.disabled is True


def test_button_variant_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        ButtonComponentData(label="x", variant="huge")  # type: ignore[arg-type]
