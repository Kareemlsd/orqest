"""Tests for RecoveryAction + WatchdogHook + default_policy."""

from __future__ import annotations

import pytest

from orqest.healing import (
    AbortRun,
    Detection,
    DiscoverAndRetry,
    EscalateToUser,
    LoopDetector,
    RegressionDetector,
    RetryDifferentModel,
    RetrySameTool,
    StallDetector,
    WatchdogHook,
    default_policy,
)
from orqest.hooks import Abort, Continue, HookAbortError, HookRunner, Redirect, Skip
from orqest.observability.events import AgentEvent, EventBus


# ---- default_policy ---------------------------------------------------


def test_policy_stall_to_abort():
    det = Detection(detector="stall", summary="x")
    action = default_policy(det)
    assert isinstance(action, AbortRun)


def test_policy_loop_to_abort():
    det = Detection(detector="loop", summary="x")
    action = default_policy(det)
    assert isinstance(action, AbortRun)


def test_policy_regression_to_abort():
    det = Detection(detector="regression", summary="x")
    action = default_policy(det)
    assert isinstance(action, AbortRun)


def test_policy_unknown_detector_to_abort():
    det = Detection(detector="custom_foo", summary="x")
    action = default_policy(det)
    assert isinstance(action, AbortRun)
    assert "custom_foo" in action.reason


# ---- WatchdogHook -----------------------------------------------------


class _FakeWatchdog:
    name = "fake"

    def __init__(self, det: Detection | None) -> None:
        self._det = det
        self._fired = False

    def subscribe(self, bus: EventBus) -> None:
        pass

    async def signal(self) -> Detection | None:
        if self._fired:
            return None
        self._fired = True
        return self._det


@pytest.mark.asyncio
async def test_watchdog_hook_no_detection_returns_continue():
    hook = WatchdogHook([_FakeWatchdog(None)])
    decision = await hook.before_tool("x", {}, None)
    assert isinstance(decision, Continue)


@pytest.mark.asyncio
async def test_watchdog_hook_abort_action_yields_abort_decision():
    det = Detection(detector="loop", summary="loop loop")
    hook = WatchdogHook([_FakeWatchdog(det)])
    runner = HookRunner([hook])
    with pytest.raises(HookAbortError):
        await runner.run_before("x", {}, None)


@pytest.mark.asyncio
async def test_watchdog_hook_retry_diff_model_yields_redirect():
    """Custom policy returning RetryDifferentModel translates to Redirect."""
    det = Detection(detector="loop", summary="x")

    def policy(d: Detection):
        return RetryDifferentModel(model="anthropic:claude-sonnet-4-6")

    hook = WatchdogHook([_FakeWatchdog(det)], policy=policy)
    decision = await hook.before_tool("t", {"a": 1}, None)
    assert isinstance(decision, Redirect)
    assert decision.new_args["_model"] == "anthropic:claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_watchdog_hook_discover_yields_redirect_with_capability():
    det = Detection(detector="loop", summary="x")

    def policy(d):
        return DiscoverAndRetry(capability="run_browser")

    hook = WatchdogHook([_FakeWatchdog(det)], policy=policy)
    decision = await hook.before_tool("t", {}, None)
    assert isinstance(decision, Redirect)
    assert decision.new_args["_discover_capability"] == "run_browser"


@pytest.mark.asyncio
async def test_watchdog_hook_escalate_yields_skip():
    det = Detection(detector="stall", summary="x")

    def policy(d):
        return EscalateToUser(question="Should I continue?")

    hook = WatchdogHook([_FakeWatchdog(det)], policy=policy)
    decision = await hook.before_tool("t", {}, None)
    assert isinstance(decision, Skip)
    assert decision.stub_result["escalation_question"] == "Should I continue?"


@pytest.mark.asyncio
async def test_watchdog_hook_retry_same_yields_continue():
    det = Detection(detector="stall", summary="x")

    def policy(d):
        return RetrySameTool(note="retry it")

    hook = WatchdogHook([_FakeWatchdog(det)], policy=policy)
    decision = await hook.before_tool("t", {}, None)
    assert isinstance(decision, Continue)


@pytest.mark.asyncio
async def test_watchdog_hook_emits_healing_action_event():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("healing.action", lambda e: captured.append(e))

    det = Detection(detector="loop", summary="loop x", payload={"foo": 1})
    hook = WatchdogHook([_FakeWatchdog(det)], bus=bus)
    runner = HookRunner([hook])
    with pytest.raises(HookAbortError):
        await runner.run_before("t", {}, None)
    assert len(captured) == 1
    assert captured[0].data["detection"]["detector"] == "loop"


@pytest.mark.asyncio
async def test_watchdog_hook_after_tool_returns_none():
    """After-tool / on-error return None — decisions only on before_tool."""
    hook = WatchdogHook([_FakeWatchdog(None)])
    assert not hasattr(hook, "after_tool") or (
        await getattr(hook, "after_tool", lambda *a, **kw: None)("x", {}, "r", None, 0.0)
        is None
    )


@pytest.mark.asyncio
async def test_watchdog_hook_swallows_signal_exceptions():
    class _Crashy:
        name = "crashy"

        def subscribe(self, bus):
            pass

        async def signal(self):
            raise RuntimeError("boom")

    hook = WatchdogHook([_Crashy()])
    decision = await hook.before_tool("t", {}, None)
    assert isinstance(decision, Continue)


@pytest.mark.asyncio
async def test_watchdog_hook_swallows_policy_exceptions():
    det = Detection(detector="x", summary="y")

    def bad_policy(d):
        raise RuntimeError("policy crash")

    hook = WatchdogHook([_FakeWatchdog(det)], policy=bad_policy)
    decision = await hook.before_tool("t", {}, None)
    assert isinstance(decision, Continue)
