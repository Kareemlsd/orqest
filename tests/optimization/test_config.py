"""Tests for OptimizationConfig."""

from __future__ import annotations

import pytest

from orqest.optimization import MetricWeights, OptimizationConfig


def test_defaults():
    cfg = OptimizationConfig()
    assert cfg.max_metric_calls == 150
    assert cfg.reflection_model is None
    assert cfg.minibatch_size == 3
    assert cfg.valset_fraction == 0.3
    assert isinstance(cfg.weights, MetricWeights)
    assert cfg.seed == 42
    assert cfg.dry_run_default is True
    assert cfg.enable_scalar_genes is False
    assert cfg.enable_categorical_genes is False
    assert cfg.cache_evaluations is True
    assert cfg.emit_per_example_events is False
    assert cfg.frontier_type == "hybrid"


def test_frozen():
    cfg = OptimizationConfig()
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.max_metric_calls = 50  # type: ignore[misc]


def test_max_metric_calls_must_be_positive():
    with pytest.raises(ValueError, match="max_metric_calls must be > 0"):
        OptimizationConfig(max_metric_calls=0)
    with pytest.raises(ValueError, match="max_metric_calls must be > 0"):
        OptimizationConfig(max_metric_calls=-5)


def test_minibatch_size_must_be_positive():
    with pytest.raises(ValueError, match="minibatch_size must be >= 1"):
        OptimizationConfig(minibatch_size=0)


def test_valset_fraction_in_open_unit_interval():
    with pytest.raises(ValueError, match="valset_fraction must be in"):
        OptimizationConfig(valset_fraction=0.0)
    with pytest.raises(ValueError, match="valset_fraction must be in"):
        OptimizationConfig(valset_fraction=1.0)
    with pytest.raises(ValueError, match="valset_fraction must be in"):
        OptimizationConfig(valset_fraction=-0.1)


def test_frontier_type_validated():
    with pytest.raises(ValueError, match="frontier_type must be one of"):
        OptimizationConfig(frontier_type="invalid")  # type: ignore[arg-type]


def test_seed_none_allowed():
    cfg = OptimizationConfig(seed=None)
    assert cfg.seed is None


def test_custom_weights_accepted():
    weights = MetricWeights(accuracy=2.0, cost_usd=-0.5)
    cfg = OptimizationConfig(weights=weights)
    assert cfg.weights.accuracy == 2.0
    assert cfg.weights.cost_usd == -0.5


def test_disabled_scalar_categorical_default():
    cfg = OptimizationConfig()
    assert cfg.enable_scalar_genes is False
    assert cfg.enable_categorical_genes is False


def test_reflection_model_override():
    cfg = OptimizationConfig(reflection_model="anthropic:claude-opus-4-7")
    assert cfg.reflection_model == "anthropic:claude-opus-4-7"
