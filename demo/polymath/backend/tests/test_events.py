"""Tests for the SSE sidecar — replay, typed events, reconnection semantics.

We don't exercise the route through httpx's ASGI streaming because an
infinite SSE generator holds the async context open across the test
boundary and deadlocks the runner. The route itself is a one-line
passthrough to :func:`orqest.observability.sse_sidecar` so we test
the generator contract directly.
"""

from __future__ import annotations

import asyncio

import pytest

from orqest.observability import AgentEvent, EventBus, sse_sidecar


@pytest.mark.asyncio
async def test_sidecar_replay_emits_historical_events() -> None:
    """Events published BEFORE a connect are emitted as a replay burst."""
    bus = EventBus()
    replay = [
        AgentEvent(event_type="test.one", agent_name="t", data={"n": 1}),
        AgentEvent(event_type="test.two", agent_name="t", data={"n": 2}),
        AgentEvent(event_type="test.three", agent_name="t", data={"n": 3}),
    ]

    lines: list[str] = []

    async def drain() -> None:
        async for chunk in sse_sidecar(bus, replay=replay, heartbeat_s=60.0):
            lines.append(chunk)
            if sum(1 for ln in lines if "event: test." in ln) >= 3:
                return

    await asyncio.wait_for(drain(), timeout=2.0)
    joined = "".join(lines)
    assert "event: test.one" in joined
    assert "event: test.two" in joined
    assert "event: test.three" in joined
    assert "id: replay-1" in joined


@pytest.mark.asyncio
async def test_sidecar_propagates_live_events() -> None:
    """An event emitted while a client is subscribed is delivered."""
    bus = EventBus()

    async def publisher() -> None:
        await asyncio.sleep(0.05)
        await bus.emit(AgentEvent(event_type="live.tick", agent_name="t", data={}))

    lines: list[str] = []

    async def drain() -> None:
        async for chunk in sse_sidecar(bus, replay=(), heartbeat_s=60.0):
            lines.append(chunk)
            if any("event: live.tick" in ln for ln in lines):
                return

    await asyncio.wait_for(
        asyncio.gather(drain(), publisher()), timeout=2.0
    )
    assert any("event: live.tick" in ln for ln in lines)


@pytest.mark.asyncio
async def test_events_route_is_registered() -> None:
    """The FastAPI route `/sessions/{sid}/events` is wired on the app.

    We inspect the app directly rather than opening a stream; hitting the
    endpoint over HTTP and then trying to close a hanging SSE body is what
    caused the previous deadlock.
    """
    from polymath.server import app

    paths = {getattr(r, "path", None) for r in app.router.routes}
    assert "/sessions/{sid}/events" in paths
