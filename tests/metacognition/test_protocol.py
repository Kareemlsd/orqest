"""Tests for ConfidenceProtocol implementations."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from orqest.metacognition import (
    EnrichedOutput,
    EnsembleProtocol,
    StructuredOutputProtocol,
)
from orqest.metacognition.protocol import (
    LLMSelfRatingProtocol,
    _coerce_confidence,
    _default_agreement,
)


class _Out(BaseModel):
    answer: str
    self_confidence: float | None = None
    uncertain_about: list[str] = []
    outside_my_capability: bool = False


# ---- helpers ----------------------------------------------------------


class TestCoerceConfidence:
    def test_none(self):
        assert _coerce_confidence(None) is None

    def test_in_range(self):
        assert _coerce_confidence(0.5) == 0.5

    def test_negative_clamped(self):
        assert _coerce_confidence(-0.3) == 0.0

    def test_above_one_clamped(self):
        assert _coerce_confidence(1.5) == 1.0

    def test_non_numeric(self):
        assert _coerce_confidence("not-a-number") is None

    def test_int_works(self):
        assert _coerce_confidence(1) == 1.0


class TestDefaultAgreement:
    def test_all_equal_returns_one(self):
        assert _default_agreement(["a", "a", "a"]) == 1.0

    def test_all_distinct_returns_zero(self):
        assert _default_agreement(["a", "b", "c"]) == 0.0

    def test_partial_agreement(self):
        # 4 samples, 1 matching pair (a,a) out of 6 pairs → ~0.167
        score = _default_agreement(["a", "a", "b", "c"])
        assert 0.15 <= score <= 0.2

    def test_single_sample_returns_one(self):
        assert _default_agreement(["a"]) == 1.0


# ---- StructuredOutputProtocol -----------------------------------------


@pytest.mark.asyncio
async def test_structured_lifts_confidence():
    p = StructuredOutputProtocol()
    out = _Out(answer="42", self_confidence=0.9, uncertain_about=["x"])
    enriched = await p.enrich(None, None, out)  # type: ignore[arg-type]
    assert enriched.confidence == 0.9
    assert enriched.uncertainty_targets == ["x"]
    assert enriched.protocol_name == "structured"
    assert enriched.output is out


@pytest.mark.asyncio
async def test_structured_missing_field_yields_none():
    p = StructuredOutputProtocol()
    out = _Out(answer="x")  # no self_confidence
    enriched = await p.enrich(None, None, out)  # type: ignore[arg-type]
    assert enriched.confidence is None


@pytest.mark.asyncio
async def test_structured_custom_field_names():
    class _Custom(BaseModel):
        answer: str
        my_score: float = 0.7
        my_unsure: list[str] = ["x"]
        my_oob: bool = True

    p = StructuredOutputProtocol(
        confidence_field="my_score",
        uncertainty_field="my_unsure",
        boundary_field="my_oob",
    )
    enriched = await p.enrich(None, None, _Custom(answer="x"))  # type: ignore[arg-type]
    assert enriched.confidence == 0.7
    assert enriched.uncertainty_targets == ["x"]
    assert enriched.capability_boundary is True


@pytest.mark.asyncio
async def test_structured_non_numeric_confidence_yields_none():
    class _Bad(BaseModel):
        answer: str
        self_confidence: str = "high"

    enriched = await StructuredOutputProtocol().enrich(None, None, _Bad(answer="x"))  # type: ignore[arg-type]
    assert enriched.confidence is None


# ---- EnsembleProtocol -------------------------------------------------


class _StubAgent:
    """Minimal `BaseAgent`-compatible duck for ensemble tests."""

    def __init__(self, samples: list[str]) -> None:
        self.samples = list(samples)
        self.calls = 0

    async def _run_implementation(self, state, **kw):
        # Pop one sample per call.
        s = self.samples[self.calls]
        self.calls += 1
        return s


@pytest.mark.asyncio
async def test_ensemble_k_must_be_at_least_two():
    with pytest.raises(ValueError):
        EnsembleProtocol(k=1)


@pytest.mark.asyncio
async def test_ensemble_all_match_confidence_one():
    p = EnsembleProtocol(k=3)
    agent = _StubAgent(["x", "x"])  # 2 extra calls (k-1)
    enriched = await p.enrich(agent, None, "x")  # type: ignore[arg-type]
    assert enriched.confidence == 1.0
    assert enriched.protocol_name == "ensemble"
    assert enriched.metadata["sample_count"] == 3


@pytest.mark.asyncio
async def test_ensemble_all_distinct_confidence_zero():
    p = EnsembleProtocol(k=3)
    agent = _StubAgent(["b", "c"])
    enriched = await p.enrich(agent, None, "a")  # type: ignore[arg-type]
    assert enriched.confidence == 0.0


@pytest.mark.asyncio
async def test_ensemble_returns_original_output_not_replacement():
    p = EnsembleProtocol(k=3)
    agent = _StubAgent(["different", "different"])
    enriched = await p.enrich(agent, None, "original")  # type: ignore[arg-type]
    assert enriched.output == "original"


@pytest.mark.asyncio
async def test_ensemble_swallows_sample_exceptions():
    """Exception in one sample doesn't tank the whole protocol."""

    class _FlakeyAgent:
        async def _run_implementation(self, state, **kw):
            raise RuntimeError("flakey")

    p = EnsembleProtocol(k=3)
    enriched = await p.enrich(_FlakeyAgent(), None, "x")  # type: ignore[arg-type]
    # Single successful sample → confidence 1.0 (only one sample, agreement vacuously true).
    assert enriched.metadata["sample_count"] == 1


# ---- LLMSelfRatingProtocol JSON parsing ------------------------------


def test_self_rating_parses_clean_json():
    payload = LLMSelfRatingProtocol._parse_rating(
        '{"confidence": 0.8, "uncertainty_targets": ["a"], "capability_boundary": false}'
    )
    assert payload["confidence"] == 0.8


def test_self_rating_strips_markdown_fences():
    payload = LLMSelfRatingProtocol._parse_rating(
        '```json\n{"confidence": 0.8}\n```'
    )
    assert payload["confidence"] == 0.8


def test_self_rating_strips_unfenced_code_block():
    payload = LLMSelfRatingProtocol._parse_rating('```\n{"confidence": 0.5}\n```')
    assert payload["confidence"] == 0.5
