"""Healing wiring tests — Phase β item 6.

Confirms that :class:`~orqest.healing.HealingRunner` is constructed by
the per-session workbench factory, registered on the HookRunner, and
configured with a fallback model when :class:`PolymathConfig`
``FALLBACK_MODELS`` is set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from orqest.healing import FallbackModel, HealingRunner
from orqest.healing.recovery import WatchdogHook


@pytest_asyncio.fixture(autouse=True)
async def _reset_config_and_runtimes() -> AsyncIterator[None]:
    """Each test rebuilds the cached ``PolymathConfig`` so env overrides
    flow into ``build_workbench``. Runtimes are torn down to stop the
    healing poll loop cleanly between cases."""
    from polymath import config as config_module
    from polymath import runtime as runtime_module

    config_module.get_default_config.cache_clear()
    yield
    # Stop poll loops before the next test populates a fresh runtime cache.
    for sid in list(runtime_module._runtimes.keys()):
        await runtime_module.drop_runtime(sid)
    config_module.get_default_config.cache_clear()


@pytest.mark.asyncio
async def test_healing_runner_in_session_runtime() -> None:
    """``get_runtime`` returns a SessionRuntime whose ``healing_runner``
    is a real :class:`HealingRunner` when ``ENABLE_HEALING`` is True
    (the demo default)."""
    from polymath import runtime as runtime_module

    rt = runtime_module.get_runtime("healing-on-sid")
    assert rt.healing_runner is not None
    assert isinstance(rt.healing_runner, HealingRunner)


@pytest.mark.asyncio
async def test_healing_disabled_yields_no_runner(monkeypatch) -> None:
    """``ENABLE_HEALING=0`` produces a runtime with ``healing_runner=None``
    and only the three observation/gate hooks on the HookRunner."""
    from polymath import config as config_module
    from polymath import runtime as runtime_module

    monkeypatch.setenv("POLYMATH_ENABLE_HEALING", "0")
    config_module.get_default_config.cache_clear()

    rt = runtime_module.get_runtime("healing-off-sid")
    assert rt.healing_runner is None
    assert len(rt.hook_runner._hooks) == 3  # event-bus + metacog + takeover


@pytest.mark.asyncio
async def test_workbench_hooks_include_watchdog_hook() -> None:
    """When healing is enabled, the HookRunner contains the runner's
    :class:`WatchdogHook` as its last hook (after takeover gate)."""
    from polymath import runtime as runtime_module

    rt = runtime_module.get_runtime("watchdog-hook-sid")
    assert rt.healing_runner is not None
    hooks = rt.hook_runner._hooks
    assert any(isinstance(h, WatchdogHook) for h in hooks)
    # Order: EventBus -> Metacog -> TakeoverGate -> WatchdogHook.
    assert isinstance(hooks[-1], WatchdogHook)


@pytest.mark.asyncio
async def test_fallback_model_used_when_configured(monkeypatch) -> None:
    """``POLYMATH_FALLBACK_MODELS`` produces a non-None
    ``runtime.healing_runner.model`` of type :class:`FallbackModel`.

    Two providers are configured (openai then anthropic) so resolution
    succeeds for both with the conftest's stub OpenAI key + a fake
    anthropic key set here."""
    from polymath import config as config_module
    from polymath import runtime as runtime_module

    monkeypatch.setenv(
        "POLYMATH_FALLBACK_MODELS", "openai:gpt-4o,anthropic:claude-sonnet-4-6"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-never-real")
    config_module.get_default_config.cache_clear()

    cfg = config_module.get_default_config()
    assert cfg.FALLBACK_MODELS == (
        "openai:gpt-4o",
        "anthropic:claude-sonnet-4-6",
    )

    rt = runtime_module.get_runtime("fallback-sid")
    assert rt.healing_runner is not None
    assert rt.healing_runner.model is not None
    assert isinstance(rt.healing_runner.model, FallbackModel)


@pytest.mark.asyncio
async def test_no_fallback_model_when_unset() -> None:
    """Empty ``FALLBACK_MODELS`` (the default) yields
    ``healing_runner.model is None`` — the agent should fall back to
    :func:`resolve_model` in :class:`PolymathAgent`."""
    from polymath import runtime as runtime_module

    rt = runtime_module.get_runtime("no-fallback-sid")
    assert rt.healing_runner is not None
    assert rt.healing_runner.model is None


@pytest.mark.asyncio
async def test_ensure_started_idempotent() -> None:
    """``SessionRuntime.ensure_started`` may be called multiple times
    without leaking poll tasks."""
    from polymath import runtime as runtime_module

    rt = runtime_module.get_runtime("ensure-started-sid")
    await rt.ensure_started()
    await rt.ensure_started()  # must not raise / double-start
    assert rt._started is True


@pytest.mark.asyncio
async def test_drop_runtime_stops_healing_poll() -> None:
    """``drop_runtime`` shuts the runner cleanly so no asyncio task
    survives session teardown."""
    from polymath import runtime as runtime_module

    rt = runtime_module.get_runtime("shutdown-sid")
    await rt.ensure_started()
    assert rt._started is True
    await runtime_module.drop_runtime("shutdown-sid")
    assert "shutdown-sid" not in runtime_module._runtimes
    # Internal task is None after stop().
    assert rt.healing_runner is not None
    assert rt.healing_runner._poll_task is None
