"""Tests for ``BadgeComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import BadgeComponent, BadgeComponentData


def test_badge_component_default_tone() -> None:
    spec = BadgeComponent(data=BadgeComponentData(label="ok"))
    assert spec.component_type == "badge"
    assert spec.data.tone == "default"
    assert spec.data.icon is None


def test_badge_round_trip_with_tone_and_icon() -> None:
    spec = BadgeComponent(
        data=BadgeComponentData(
            label="warning", tone="warning", icon="alert-triangle"
        )
    )
    revived = BadgeComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.label == "warning"
    assert revived.data.tone == "warning"
    assert revived.data.icon == "alert-triangle"


def test_badge_tone_literal_enforced() -> None:
    with pytest.raises(ValidationError):
        BadgeComponentData(label="x", tone="neon")  # type: ignore[arg-type]
