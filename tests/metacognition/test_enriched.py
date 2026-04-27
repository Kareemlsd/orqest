"""Tests for EnrichedOutput[T]."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from orqest.metacognition import EnrichedOutput


class _Out(BaseModel):
    answer: str


class TestEnrichedOutputShape:
    def test_minimal_construction(self):
        e = EnrichedOutput(output=_Out(answer="42"))
        assert e.output.answer == "42"
        assert e.confidence is None
        assert e.uncertainty_targets == []
        assert e.capability_boundary is False
        assert e.protocol_name is None
        assert e.metadata == {}

    def test_full_construction(self):
        e = EnrichedOutput(
            output=_Out(answer="42"),
            confidence=0.7,
            uncertainty_targets=["assumption_X", "data_freshness"],
            capability_boundary=True,
            protocol_name="structured",
            metadata={"sample_count": 3},
        )
        assert e.confidence == 0.7
        assert "assumption_X" in e.uncertainty_targets
        assert e.capability_boundary is True
        assert e.protocol_name == "structured"

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            EnrichedOutput(output=_Out(answer="x"), confidence=1.5)
        with pytest.raises(ValidationError):
            EnrichedOutput(output=_Out(answer="x"), confidence=-0.1)

    def test_confidence_zero_and_one_accepted(self):
        EnrichedOutput(output=_Out(answer="x"), confidence=0.0)
        EnrichedOutput(output=_Out(answer="x"), confidence=1.0)

    def test_round_trip_via_json(self):
        original = EnrichedOutput(
            output=_Out(answer="hi"),
            confidence=0.42,
            uncertainty_targets=["a", "b"],
            capability_boundary=False,
            protocol_name="ensemble",
            metadata={"k": 3},
        )
        blob = original.model_dump_json()
        revived = EnrichedOutput[_Out].model_validate_json(blob)
        assert revived.output.answer == "hi"
        assert revived.confidence == 0.42
        assert revived.uncertainty_targets == ["a", "b"]
        assert revived.protocol_name == "ensemble"

    def test_output_is_required(self):
        with pytest.raises(ValidationError):
            EnrichedOutput()  # type: ignore[call-arg]
