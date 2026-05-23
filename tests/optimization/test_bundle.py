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


# --- aggregate() + trial-variance tests --------------------------------


def test_aggregate_empty_raises():
    with pytest.raises(ValueError, match="at least one bundle"):
        MetricBundle.aggregate([])


def test_aggregate_single_bundle_returns_unchanged():
    b = MetricBundle(accuracy=0.7, confidence=0.5, cost_usd=0.01, latency_ms=200.0)
    agg = MetricBundle.aggregate([b])
    # Single observation: returned unchanged; n_trials still 1; no stdev.
    assert agg is b
    assert agg.n_trials == 1
    assert agg.stdev is None


def test_aggregate_two_bundles_computes_mean_and_stdev():
    b1 = MetricBundle(accuracy=0.6, cost_usd=0.01, latency_ms=100.0)
    b2 = MetricBundle(accuracy=1.0, cost_usd=0.05, latency_ms=300.0)
    agg = MetricBundle.aggregate([b1, b2])
    assert agg.n_trials == 2
    assert agg.accuracy == pytest.approx(0.8)
    assert agg.cost_usd == pytest.approx(0.03)
    assert agg.latency_ms == pytest.approx(200.0)
    assert agg.stdev is not None
    # statistics.stdev([0.6, 1.0]) == 0.2828...
    assert agg.stdev["accuracy"] == pytest.approx(0.28284271247461906)
    assert agg.stdev["cost_usd"] == pytest.approx(0.028284271247461906)


def test_aggregate_handles_optional_dimensions_uniformly_present():
    bundles = [
        MetricBundle(accuracy=0.5, confidence=0.4, robustness=0.7),
        MetricBundle(accuracy=0.9, confidence=0.8, robustness=0.9),
        MetricBundle(accuracy=0.7, confidence=0.6, robustness=0.5),
    ]
    agg = MetricBundle.aggregate(bundles)
    assert agg.n_trials == 3
    assert agg.confidence == pytest.approx(0.6)
    assert agg.robustness == pytest.approx(0.7)
    assert "confidence" in agg.stdev  # type: ignore[operator]
    assert "robustness" in agg.stdev  # type: ignore[operator]


def test_aggregate_handles_optional_dimensions_partially_present():
    # confidence present in 2/3 trials; robustness present in 1/3
    bundles = [
        MetricBundle(accuracy=0.5, confidence=0.4, robustness=None),
        MetricBundle(accuracy=0.9, confidence=0.8, robustness=None),
        MetricBundle(accuracy=0.7, confidence=None, robustness=0.6),
    ]
    agg = MetricBundle.aggregate(bundles)
    # confidence: mean over present values (0.4 + 0.8) / 2 = 0.6
    assert agg.confidence == pytest.approx(0.6)
    # robustness: only one present value — that becomes the mean
    assert agg.robustness == pytest.approx(0.6)
    # stdev requires >= 2 samples: confidence yes, robustness no
    assert "confidence" in agg.stdev  # type: ignore[operator]
    assert "robustness" not in agg.stdev  # type: ignore[operator]


def test_aggregate_optional_dimensions_uniformly_absent():
    bundles = [
        MetricBundle(accuracy=0.5, confidence=None, robustness=None),
        MetricBundle(accuracy=0.7, confidence=None, robustness=None),
    ]
    agg = MetricBundle.aggregate(bundles)
    assert agg.confidence is None
    assert agg.robustness is None
    assert "confidence" not in agg.stdev  # type: ignore[operator]
    assert "robustness" not in agg.stdev  # type: ignore[operator]


def test_aggregate_preserves_first_bundles_raw_as_representative():
    bundles = [
        MetricBundle(accuracy=0.5, raw={"counter": 7, "first": True}),
        MetricBundle(accuracy=0.7, raw={"counter": 3, "second": True}),
    ]
    agg = MetricBundle.aggregate(bundles)
    # Consumer owns merge semantics; we keep first as a representative sample.
    assert agg.raw == {"counter": 7, "first": True}


def test_aggregated_bundle_scalarizes_normally():
    """An aggregated bundle behaves like any other for downstream scoring."""
    bundles = [
        MetricBundle(accuracy=0.8, cost_usd=0.01, latency_ms=200.0),
        MetricBundle(accuracy=1.0, cost_usd=0.02, latency_ms=300.0),
    ]
    agg = MetricBundle.aggregate(bundles)
    w = MetricWeights()
    score = agg.scalarize(w)
    # mean accuracy 0.9, cost 0.015, latency 250 → 0.9 - 0.15 - 0.005 ≈ 0.745
    assert score == pytest.approx(0.9 - 0.015 * 10 - 250 * 0.00002, abs=1e-6)


def test_aggregated_bundle_round_trips_through_pydantic_serialization():
    """Aggregate bundle must survive model_dump → model_validate cycle so
    consumers can persist it (cache, event payload, ...)"""
    bundles = [
        MetricBundle(accuracy=0.6, confidence=0.7),
        MetricBundle(accuracy=0.9, confidence=0.5),
    ]
    agg = MetricBundle.aggregate(bundles)
    dumped = agg.model_dump()
    assert dumped["n_trials"] == 2
    assert "accuracy" in dumped["stdev"]
    rebuilt = MetricBundle.model_validate(dumped)
    assert rebuilt.n_trials == 2
    assert rebuilt.stdev == agg.stdev
    assert rebuilt.accuracy == agg.accuracy


def test_bundle_defaults_preserve_backward_compat():
    """A bundle constructed without the new fields behaves exactly as before."""
    b = MetricBundle(accuracy=0.5)
    assert b.n_trials == 1
    assert b.stdev is None
    # Round-trip still produces the same shape
    rebuilt = MetricBundle.model_validate(b.model_dump())
    assert rebuilt == b
