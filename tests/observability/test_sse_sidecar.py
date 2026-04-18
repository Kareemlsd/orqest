"""Tests for sse_sidecar."""

from __future__ import annotations

import asyncio
import json

import pytest

from orqest.observability import AgentEvent, EventBus, sse_sidecar


def _parse_sse(chunk: str) -> dict[str, str]:
    """Parse one SSE chunk into a dict of its lines."""
    out: dict[str, str] = {}
    for line in chunk.rstrip("\n").split("\n"):
        if line.startswith(":"):
            out.setdefault("_comment", line[1:].strip())
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.lstrip()
    return out


class TestLiveStreaming:
    @pytest.mark.asyncio
    async def test_event_is_emitted_as_sse_chunk(self):
        bus = EventBus()
        agen = sse_sidecar(bus, heartbeat_s=10.0)

        # Kick the iterator so it subscribes
        task = asyncio.create_task(agen.__anext__())
        await asyncio.sleep(0.01)

        await bus.emit(
            AgentEvent(
                event_type="tool.before",
                agent_name="demo",
                data={"tool_name": "generate_mesh"},
            )
        )

        chunk = await asyncio.wait_for(task, timeout=1.0)
        parsed = _parse_sse(chunk)
        assert parsed["event"] == "tool.before"
        assert "id" in parsed
        payload = json.loads(parsed["data"])
        assert payload["event_type"] == "tool.before"
        assert payload["agent_name"] == "demo"
        assert payload["data"]["tool_name"] == "generate_mesh"

        await agen.aclose()

    @pytest.mark.asyncio
    async def test_multiple_events_arrive_in_order(self):
        bus = EventBus()
        agen = sse_sidecar(bus, heartbeat_s=10.0)

        for i in range(3):
            await bus.emit(
                AgentEvent(event_type="tool.after", agent_name="x", data={"i": i})
            )

        received: list[int] = []
        for _ in range(3):
            chunk = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
            received.append(json.loads(_parse_sse(chunk)["data"])["data"]["i"])

        assert received == [0, 1, 2]
        await agen.aclose()


class TestReplay:
    @pytest.mark.asyncio
    async def test_replay_comes_first(self):
        bus = EventBus()
        historic = [
            AgentEvent(event_type="tool.before", agent_name="x", data={"r": 1}),
            AgentEvent(event_type="tool.after", agent_name="x", data={"r": 2}),
        ]
        agen = sse_sidecar(bus, replay=historic, heartbeat_s=10.0)

        first = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
        second = await asyncio.wait_for(agen.__anext__(), timeout=1.0)

        assert _parse_sse(first)["id"].startswith("replay-")
        assert json.loads(_parse_sse(first)["data"])["data"]["r"] == 1
        assert json.loads(_parse_sse(second)["data"])["data"]["r"] == 2

        await agen.aclose()


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_emits_comment_on_idle(self):
        bus = EventBus()
        agen = sse_sidecar(bus, heartbeat_s=0.05)

        chunk = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
        assert chunk == ": keep-alive\n\n"

        await agen.aclose()


class TestBackpressure:
    @pytest.mark.asyncio
    async def test_slow_consumer_drops_oldest_not_newest(self):
        bus = EventBus()
        agen = sse_sidecar(bus, heartbeat_s=10.0, queue_size=2)

        # Drain one chunk to subscribe, then pause consumption
        await bus.emit(AgentEvent(event_type="t", agent_name="x", data={"n": 0}))
        first = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
        assert json.loads(_parse_sse(first)["data"])["data"]["n"] == 0

        # Flood: queue=2, fourth should push oldest out
        for i in range(1, 5):
            await bus.emit(AgentEvent(event_type="t", agent_name="x", data={"n": i}))

        remaining: list[int] = []
        for _ in range(2):
            chunk = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
            remaining.append(json.loads(_parse_sse(chunk)["data"])["data"]["n"])

        # Newest (4, 3) survive; oldest (1, 2) dropped
        assert 4 in remaining
        assert 1 not in remaining

        await agen.aclose()


class TestCleanup:
    @pytest.mark.asyncio
    async def test_unsubscribes_on_close(self):
        bus = EventBus()
        before = len(bus._global_handlers)
        agen = sse_sidecar(bus, heartbeat_s=10.0)

        # Prime subscription
        await bus.emit(AgentEvent(event_type="t", agent_name="x"))
        await asyncio.wait_for(agen.__anext__(), timeout=1.0)
        assert len(bus._global_handlers) == before + 1

        await agen.aclose()
        assert len(bus._global_handlers) == before
