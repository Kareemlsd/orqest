"""Tests for StallDetector / LoopDetector / RegressionDetector."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from orqest.healing import (
    LoopDetector,
    RegressionDetector,
    StallDetector,
)
from orqest.observability.events import AgentEvent, EventBus


def _evt(event_type: str, **data) -> AgentEvent:
    return AgentEvent(event_type=event_type, agent_name="test", data=data)


# ---- StallDetector ----------------------------------------------------


@pytest.mark.asyncio
async def test_stall_no_open_calls_returns_none():
    wd = StallDetector(timeout_s=1.0)
    assert await wd.signal() is None


@pytest.mark.asyncio
async def test_stall_call_closed_within_timeout_no_signal():
    bus = EventBus()
    wd = StallDetector(timeout_s=10.0)
    wd.subscribe(bus)
    await bus.emit(_evt("tool.before", tool_name="x"))
    await bus.emit(_evt("tool.after", tool_name="x"))
    assert await wd.signal() is None


@pytest.mark.asyncio
async def test_stall_call_exceeds_timeout_signals_detection():
    bus = EventBus()
    wd = StallDetector(timeout_s=0.05)
    wd.subscribe(bus)
    await bus.emit(_evt("tool.before", tool_name="x"))
    await asyncio.sleep(0.1)
    detection = await wd.signal()
    assert detection is not None
    assert detection.detector == "stall"
    assert detection.payload["call_id"].startswith("x::")


@pytest.mark.asyncio
async def test_stall_does_not_double_fire_for_same_call():
    bus = EventBus()
    wd = StallDetector(timeout_s=0.05)
    wd.subscribe(bus)
    await bus.emit(_evt("tool.before", tool_name="x"))
    await asyncio.sleep(0.1)
    first = await wd.signal()
    second = await wd.signal()
    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_stall_subscribe_idempotent():
    bus = EventBus()
    wd = StallDetector(timeout_s=10.0)
    wd.subscribe(bus)
    wd.subscribe(bus)
    # Two subscribes should not double-track.
    await bus.emit(_evt("tool.before", tool_name="x"))
    assert len(wd._open_calls) == 1


# ---- LoopDetector -----------------------------------------------------


@pytest.mark.asyncio
async def test_loop_below_threshold_no_signal():
    bus = EventBus()
    wd = LoopDetector(threshold_k=3, window_n=10)
    wd.subscribe(bus)
    for _ in range(2):
        await bus.emit(_evt("tool.before", tool_name="x", args={"a": 1}))
    assert await wd.signal() is None


@pytest.mark.asyncio
async def test_loop_at_threshold_plus_one_fires():
    bus = EventBus()
    wd = LoopDetector(threshold_k=2, window_n=10)
    wd.subscribe(bus)
    for _ in range(3):
        await bus.emit(_evt("tool.before", tool_name="x", args={"a": 1}))
    detection = await wd.signal()
    assert detection is not None
    assert detection.payload["count"] == 3
    assert detection.payload["tool_name"] == "x"


@pytest.mark.asyncio
async def test_loop_distinct_args_no_trigger():
    bus = EventBus()
    wd = LoopDetector(threshold_k=2, window_n=10)
    wd.subscribe(bus)
    for i in range(5):
        await bus.emit(_evt("tool.before", tool_name="x", args={"i": i}))
    assert await wd.signal() is None


@pytest.mark.asyncio
async def test_loop_window_slides():
    bus = EventBus()
    wd = LoopDetector(threshold_k=2, window_n=3)
    wd.subscribe(bus)
    # 3 same calls — would fire.
    for _ in range(3):
        await bus.emit(_evt("tool.before", tool_name="x", args={"a": 1}))
    first = await wd.signal()
    assert first is not None
    # Now flush the window with different calls.
    for i in range(3):
        await bus.emit(_evt("tool.before", tool_name="y", args={"i": i}))
    # No new fire for the original pair.
    assert await wd.signal() is None


@pytest.mark.asyncio
async def test_loop_suppression_until_pair_changes():
    bus = EventBus()
    wd = LoopDetector(threshold_k=2, window_n=10)
    wd.subscribe(bus)
    for _ in range(3):
        await bus.emit(_evt("tool.before", tool_name="x", args={"a": 1}))
    first = await wd.signal()
    assert first is not None
    # Same pair again, no new fire.
    await bus.emit(_evt("tool.before", tool_name="x", args={"a": 1}))
    assert await wd.signal() is None


def test_loop_invalid_config():
    with pytest.raises(ValueError):
        LoopDetector(threshold_k=0)
    with pytest.raises(ValueError):
        LoopDetector(threshold_k=5, window_n=2)


# ---- RegressionDetector -----------------------------------------------


@pytest.mark.asyncio
async def test_regression_no_events_no_signal():
    """Without metacognition events, detector silently no-ops."""
    bus = EventBus()
    wd = RegressionDetector(window_n=4)
    wd.subscribe(bus)
    assert await wd.signal() is None


@pytest.mark.asyncio
async def test_regression_below_window_n_no_signal():
    bus = EventBus()
    wd = RegressionDetector(window_n=4)
    wd.subscribe(bus)
    for c in [0.9, 0.8]:
        await bus.emit(_evt("metacognition.confidence", confidence=c))
    assert await wd.signal() is None


@pytest.mark.asyncio
async def test_regression_drop_triggers_detection():
    bus = EventBus()
    wd = RegressionDetector(window_n=4, drop_threshold=0.2)
    wd.subscribe(bus)
    # head 0.9, 0.85 → mean 0.875 ; tail 0.5, 0.4 → mean 0.45 ; drop 0.425
    for c in [0.9, 0.85, 0.5, 0.4]:
        await bus.emit(_evt("metacognition.confidence", confidence=c))
    detection = await wd.signal()
    assert detection is not None
    assert detection.detector == "regression"


@pytest.mark.asyncio
async def test_regression_stable_no_trigger():
    bus = EventBus()
    wd = RegressionDetector(window_n=4, drop_threshold=0.2)
    wd.subscribe(bus)
    for c in [0.7, 0.72, 0.71, 0.69]:
        await bus.emit(_evt("metacognition.confidence", confidence=c))
    assert await wd.signal() is None


@pytest.mark.asyncio
async def test_regression_invalid_score_ignored():
    bus = EventBus()
    wd = RegressionDetector(window_n=4)
    wd.subscribe(bus)
    await bus.emit(_evt("metacognition.confidence", confidence="not-a-number"))
    await bus.emit(_evt("metacognition.confidence", confidence=1.5))  # out of [0,1]
    assert await wd.signal() is None


def test_regression_invalid_config():
    with pytest.raises(ValueError):
        RegressionDetector(window_n=1)
    with pytest.raises(ValueError):
        RegressionDetector(drop_threshold=1.5)
