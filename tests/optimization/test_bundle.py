"""Tests for MetricBundle and MetricWeights."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.optimization import MetricBundle, MetricWeights


def test_metric_weights_defaults():
    w = MetricWeights()
    assert w.accuracy == 1.0
    assert w.confidence == 0.1
    assert w.cost_usd == -10.0
    assert w.latency_ms == -0.00002
    assert w.robustness == 0.2


def test_metric_weights_defaults_keep_accuracy_dominant():
    """Sanity: a perfect-accuracy candidate at realistic LLM cost / latency
    must end up with a positive scalar score so the optimizer sees it as
    a win. Was a real bug pre-tune (latency_ms=-0.001 dwarfed accuracy)."""
    w = MetricWeights()
    typical = MetricBundle(accuracy=1.0, cost_usd=0.005, latency_ms=5000.0)
    assert typical.scalarize(w) > 0.5  # dominated by accuracy, not penalties


def test_metric_weights_frozen():
    w = MetricWeights()
    with pytest.raises(ValidationError):
        w.accuracy = 2.0  # type: ignore[misc]


def test_bundle_pure_accuracy_scalarize():
    b = MetricBundle(accuracy=0.8)
    w = MetricWeights(accuracy=1.0, confidence=0.0, cost_usd=0.0, latency_ms=0.0, robustness=0.0)
    assert b.scalarize(w) == pytest.approx(0.8)


def test_bundle_scalarize_penalizes_cost_and_latency():
    high_cost = MetricBundle(accuracy=0.8, cost_usd=2.0, latency_ms=5000.0)
    low_cost = MetricBundle(accuracy=0.8, cost_usd=0.1, latency_ms=200.0)
    w = MetricWeights()
    assert low_cost.scalarize(w) > high_cost.scalarize(w)


def test_bundle_handles_none_confidence_and_robustness():
    """None dimensions must be skipped, not treated as zero."""
    b = MetricBundle(accuracy=0.8, confidence=None, robustness=None)
    w = MetricWeights()
    score = b.scalarize(w)
    # Should equal pure-accuracy scalarize because confidence/robustness are None
    expected = 0.8 * w.accuracy
    assert score == pytest.approx(expected)


def test_to_per_instance_scores_emits_one_per_dimension():
    b = MetricBundle(
        accuracy=0.8,
        confidence=0.7,
        cost_usd=0.5,
        latency_ms=1000.0,
        robustness=0.9,
    )
    w = MetricWeights()
    scores = b.to_per_instance_scores(w)
    assert "accuracy" in scores
    assert "confidence" in scores
    assert "cost_usd" in scores
    assert "latency_ms" in scores
    assert "robustness" in scores
    assert scores["accuracy"] == pytest.approx(0.8)


def test_to_per_instance_scores_omits_none_dimensions():
    b = MetricBundle(accuracy=0.8, confidence=None, robustness=None)
    w = MetricWeights()
    scores = b.to_per_instance_scores(w)
    assert "accuracy" in scores
    assert "confidence" not in scores
    assert "robustness" not in scores


def test_field_bounds_enforced():
    with pytest.raises(ValidationError):
        MetricBundle(accuracy=1.5)  # > 1.0
    with pytest.raises(ValidationError):
        MetricBundle(accuracy=-0.1)  # < 0.0
    with pytest.raises(ValidationError):
        MetricBundle(accuracy=0.5, confidence=2.0)
    # Negative cost / latency rejected
    with pytest.raises(ValidationError):
        MetricBundle(accuracy=0.5, cost_usd=-0.1)
