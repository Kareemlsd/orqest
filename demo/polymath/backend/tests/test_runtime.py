"""Tests for the SessionRuntime cache."""

from __future__ import annotations

import pytest

from polymath import runtime


@pytest.mark.asyncio
async def test_get_runtime_is_cached() -> None:
    """Two lookups with the same session id return the same runtime."""
    a = runtime.get_runtime("sid-a")
    b = runtime.get_runtime("sid-a")
    assert a is b


@pytest.mark.asyncio
async def test_get_runtime_different_sids_isolated() -> None:
    """Different session ids get independent runtimes (and event buses)."""
    a = runtime.get_runtime("sid-a")
    b = runtime.get_runtime("sid-b")
    assert a is not b
    assert a.workbench.event_bus is not b.workbench.event_bus


@pytest.mark.asyncio
async def test_drop_runtime_evicts() -> None:
    runtime.get_runtime("to-drop")
    assert "to-drop" in runtime._runtimes
    await runtime.drop_runtime("to-drop")
    assert "to-drop" not in runtime._runtimes


@pytest.mark.asyncio
async def test_drop_runtime_noop_on_missing() -> None:
    """Dropping an unknown sid is a silent no-op."""
    await runtime.drop_runtime("never-existed")  # must not raise


@pytest.mark.asyncio
async def test_emit_lands_on_session_bus() -> None:
    """polymath.runtime.emit publishes to the session's workbench bus."""
    rt = runtime.get_runtime("emit-sid")
    seen: list[str] = []

    async def handler(evt) -> None:
        seen.append(evt.event_type)

    rt.workbench.event_bus.subscribe_all(handler)
    await runtime.emit("emit-sid", "custom.type", {"hello": "world"})
    assert "custom.type" in seen
