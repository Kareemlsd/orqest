"""Tests for MetacognitionConfig."""

from __future__ import annotations

import pytest

from orqest.metacognition import MetacognitionConfig


def test_defaults_are_conservative():
    cfg = MetacognitionConfig()
    assert cfg.redecompose_threshold == 0.5
    assert cfg.max_redecompositions == 2
    assert cfg.confidence_floor == 0.0


def test_frozen():
    cfg = MetacognitionConfig()
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.redecompose_threshold = 0.7  # type: ignore[misc]


def test_invalid_threshold_rejected():
    with pytest.raises(ValueError):
        MetacognitionConfig(redecompose_threshold=1.5)
    with pytest.raises(ValueError):
        MetacognitionConfig(redecompose_threshold=-0.1)


def test_invalid_floor_rejected():
    with pytest.raises(ValueError):
        MetacognitionConfig(confidence_floor=2.0)


def test_negative_max_redecompositions_rejected():
    with pytest.raises(ValueError):
        MetacognitionConfig(max_redecompositions=-1)


def test_zero_max_redecompositions_allowed():
    """Zero re-decompositions is a valid 'disable' config."""
    cfg = MetacognitionConfig(max_redecompositions=0)
    assert cfg.max_redecompositions == 0
