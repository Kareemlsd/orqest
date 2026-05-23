"""Tests for HealingConfig."""

from __future__ import annotations

import pytest

from orqest.healing import HealingConfig


def test_defaults():
    cfg = HealingConfig()
    assert cfg.stall_timeout_s == 60.0
    assert cfg.loop_threshold_k == 3
    assert cfg.loop_window_n == 10
    assert cfg.regression_window_n == 5
    assert cfg.regression_drop_threshold == 0.2
    assert cfg.poll_interval_s == 1.0
    assert cfg.fallback_models == ()
    assert cfg.enable_stall is True
    assert cfg.enable_loop is True
    assert cfg.enable_regression is False  # off by default — needs metacognition


def test_frozen():
    cfg = HealingConfig()
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.stall_timeout_s = 5.0  # type: ignore[misc]


def test_invalid_stall_timeout_rejected():
    with pytest.raises(ValueError):
        HealingConfig(stall_timeout_s=0)
    with pytest.raises(ValueError):
        HealingConfig(stall_timeout_s=-1)


def test_invalid_loop_threshold_rejected():
    with pytest.raises(ValueError):
        HealingConfig(loop_threshold_k=0)


def test_window_must_be_at_least_threshold():
    with pytest.raises(ValueError):
        HealingConfig(loop_threshold_k=5, loop_window_n=3)


def test_invalid_regression_window_rejected():
    with pytest.raises(ValueError):
        HealingConfig(regression_window_n=1)


def test_invalid_drop_threshold_rejected():
    with pytest.raises(ValueError):
        HealingConfig(regression_drop_threshold=1.5)
    with pytest.raises(ValueError):
        HealingConfig(regression_drop_threshold=-0.1)
