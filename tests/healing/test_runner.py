"""Tests for HealingRunner + Workbench.with_healing."""

from __future__ import annotations

import asyncio

import pytest

from orqest.healing import (
    HealingConfig,
    HealingRunner,
    LoopDetector,
    StallDetector,
)
from orqest.observability.events import AgentEvent, EventBus


@pytest.mark.asyncio
async def test_runner_constructs_default_watchdogs():
    bus = EventBus()
    runner = HealingRunner(HealingConfig(), bus=bus)
    types = {type(wd).__name__ for wd in runner.watchdogs}
    # Stall + Loop on by default; Regression off.
    assert "StallDetector" in types
    assert "LoopDetector" in types
    assert "RegressionDetector" not in types


@pytest.mark.asyncio
async def test_runner_respects_enable_flags():
    bus = EventBus()
    runner = HealingRunner(
        HealingConfig(enable_stall=False, enable_loop=False, enable_regression=True),
        bus=bus,
    )
    types = {type(wd).__name__ for wd in runner.watchdogs}
    assert types == {"RegressionDetector"}


@pytest.mark.asyncio
async def test_runner_accepts_explicit_watchdogs():
    bus = EventBus()
    custom = [StallDetector(timeout_s=10.0)]
    runner = HealingRunner(HealingConfig(), bus=bus, watchdogs=custom)
    assert runner.watchdogs == custom


@pytest.mark.asyncio
async def test_runner_lifecycle_start_stop():
    bus = EventBus()
    runner = HealingRunner(HealingConfig(poll_interval_s=0.05), bus=bus)
    await runner.start()
    assert runner._poll_task is not None
    await asyncio.sleep(0.06)  # let one poll iteration run
    await runner.stop()
    assert runner._poll_task is None


@pytest.mark.asyncio
async def test_runner_async_context_manager():
    bus = EventBus()
    runner = HealingRunner(HealingConfig(poll_interval_s=0.05), bus=bus)
    async with runner:
        assert runner._poll_task is not None
        await asyncio.sleep(0.06)
    assert runner._poll_task is None


@pytest.mark.asyncio
async def test_runner_emits_healing_detection_events():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("healing.detection", lambda e: captured.append(e))

    cfg = HealingConfig(
        stall_timeout_s=0.05,
        enable_loop=False,
        poll_interval_s=0.02,
    )
    runner = HealingRunner(cfg, bus=bus)
    async with runner:
        await bus.emit(
            AgentEvent(
                event_type="tool.before",
                agent_name="x",
                data={"tool_name": "stuck_tool", "args": {}},
            )
        )
        await asyncio.sleep(0.15)
    assert len(captured) >= 1
    assert captured[0].agent_name == "stall"


@pytest.mark.asyncio
async def test_runner_no_fallback_when_unconfigured():
    bus = EventBus()
    runner = HealingRunner(HealingConfig(), bus=bus)
    assert runner.model is None


@pytest.mark.asyncio
async def test_runner_fallback_built_when_configured():
    bus = EventBus()
    runner = HealingRunner(
        HealingConfig(fallback_models=("openai:gpt-4o",)),
        bus=bus,
        api_key="test-key",
    )
    assert runner.model is not None


@pytest.mark.asyncio
async def test_runner_fallback_failure_logged_not_raised():
    """If the fallback chain can't resolve, runner stays usable."""
    bus = EventBus()
    runner = HealingRunner(
        HealingConfig(fallback_models=("nonsense_provider:foo",)),
        bus=bus,
        api_key="test-key",
    )
    assert runner.model is None  # gracefully None


@pytest.mark.asyncio
async def test_runner_poll_swallows_watchdog_exceptions():
    """A crashing watchdog never kills the poll loop."""
    bus = EventBus()

    class _Crashy:
        name = "crashy"

        def subscribe(self, b):
            pass

        async def signal(self):
            raise RuntimeError("boom")

    runner = HealingRunner(
        HealingConfig(poll_interval_s=0.02),
        bus=bus,
        watchdogs=[_Crashy()],
    )
    async with runner:
        await asyncio.sleep(0.06)
    # No exception escaped — the runner is still healthy.


# ---- Workbench.with_healing convenience ------------------------------


@pytest.mark.asyncio
async def test_workbench_with_healing_returns_runner():
    from orqest.workbench import Workbench

    class _MockMemory:
        async def store(self, *a, **kw):
            return "id"

        async def recall(self, *a, **kw):
            return []

    wb = Workbench(memory=_MockMemory())
    runner = wb.with_healing(HealingConfig())
    assert isinstance(runner, HealingRunner)
    assert runner._bus is wb.event_bus
