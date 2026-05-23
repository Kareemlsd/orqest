"""Tests for confidence_salience and recency_salience."""

from __future__ import annotations

from orqest.metacognition import confidence_salience, recency_salience


class _MsgWithMeta:
    """Stub message with a metadata dict (mirrors pydantic-AI v2 shape)."""

    def __init__(self, **md):
        self.metadata = dict(md)


class _MsgWithAttr:
    """Stub message exposing _age_turns directly."""

    def __init__(self, age):
        self._age_turns = age


# ---- confidence_salience ----------------------------------------------


def test_confidence_salience_no_metadata_returns_one():
    msg = _MsgWithMeta()
    assert confidence_salience(msg) == 1.0


def test_confidence_salience_returns_metadata_value():
    msg = _MsgWithMeta(metacognition_confidence=0.7)
    assert confidence_salience(msg) == 0.7


def test_confidence_salience_floor_clamps_low_values():
    msg = _MsgWithMeta(metacognition_confidence=0.05)
    assert confidence_salience(msg, floor=0.3) == 0.3


def test_confidence_salience_clamps_above_one():
    msg = _MsgWithMeta(metacognition_confidence=1.5)
    assert confidence_salience(msg) == 1.0


def test_confidence_salience_non_numeric_returns_one():
    msg = _MsgWithMeta(metacognition_confidence="high")
    assert confidence_salience(msg) == 1.0


def test_confidence_salience_custom_metadata_key():
    msg = _MsgWithMeta(my_score=0.6)
    assert confidence_salience(msg, metadata_key="my_score") == 0.6


# ---- recency_salience -------------------------------------------------


def test_recency_salience_no_age_returns_one():
    class _Bare:
        pass

    assert recency_salience(_Bare()) == 1.0


def test_recency_salience_decays_with_age():
    msg = _MsgWithAttr(age=5)
    s = recency_salience(msg, decay=0.95)
    # 0.95**5 ≈ 0.774
    assert 0.7 < s < 0.8


def test_recency_salience_zero_age_returns_one():
    msg = _MsgWithAttr(age=0)
    assert recency_salience(msg) == 1.0


def test_recency_salience_age_in_metadata():
    msg = _MsgWithMeta(_age_turns=3)
    s = recency_salience(msg, decay=0.9)
    # 0.9**3 = 0.729
    assert 0.7 < s < 0.75
