"""Tests for Workbench container primitive."""

from __future__ import annotations

import pytest

from orqest.memory import MemoryEntry
from orqest.observability import AgentEvent, EventBus, JSONTracer
from orqest.workbench import Workbench


class _FakeMemory:
    """Minimal in-memory MemoryStore for tests."""

    def __init__(self) -> None:
        self.entries: list[MemoryEntry] = []

    async def store(self, entry: MemoryEntry) -> str:
        self.entries.append(entry)
        return entry.id

    async def recall(self, query, *, k=5, filters=None):
        return [e for e in self.entries if query in e.content][:k]

    async def forget(self, entry_id):
        self.entries = [e for e in self.entries if e.id != entry_id]

    async def update_reliability(self, entry_id, *, success):
        pass

    async def count(self):
        return len(self.entries)


class TestConstruction:
    def test_defaults_create_fresh_tracer_and_bus(self):
        wb = Workbench(memory=_FakeMemory())
        assert isinstance(wb.tracer, JSONTracer)
        assert isinstance(wb.event_bus, EventBus)
        assert list(wb.recent_events) == []

    def test_custom_tracer_and_bus_preserved(self):
        tracer = JSONTracer()
        bus = EventBus()
        wb = Workbench(memory=_FakeMemory(), tracer=tracer, event_bus=bus)
        assert wb.tracer is tracer
        assert wb.event_bus is bus

    def test_memory_is_exposed_directly(self):
        mem = _FakeMemory()
        wb = Workbench(memory=mem)
        assert wb.memory is mem


class TestEventBuffering:
    @pytest.mark.asyncio
    async def test_events_populate_buffer(self):
        wb = Workbench(memory=_FakeMemory())
        await wb.event_bus.emit(
            AgentEvent(event_type="t", agent_name="x", data={"i": 1})
        )
        await wb.event_bus.emit(
            AgentEvent(event_type="t", agent_name="x", data={"i": 2})
        )

        assert len(wb.recent_events) == 2
        assert wb.recent_events[-1].data == {"i": 2}

    @pytest.mark.asyncio
    async def test_buffer_is_bounded_by_buffer_size(self):
        wb = Workbench(memory=_FakeMemory(), buffer_size=3)
        for i in range(5):
            await wb.event_bus.emit(
                AgentEvent(event_type="t", agent_name="x", data={"i": i})
            )
        assert len(wb.recent_events) == 3
        # Oldest dropped, newest kept
        assert [e.data["i"] for e in wb.recent_events] == [2, 3, 4]

    @pytest.mark.asyncio
    async def test_buffer_size_zero_disables_buffering(self):
        wb = Workbench(memory=_FakeMemory(), buffer_size=0)
        await wb.event_bus.emit(AgentEvent(event_type="t", agent_name="x"))
        assert len(wb.recent_events) == 0


class TestReset:
    @pytest.mark.asyncio
    async def test_reset_clears_events_and_tracer_but_not_memory(self):
        mem = _FakeMemory()
        await mem.store(MemoryEntry(content="persist me"))

        wb = Workbench(memory=mem)
        span = wb.tracer.start_span("work")  # type: ignore[attr-defined]
        wb.tracer.end_span(span)  # type: ignore[attr-defined]
        await wb.event_bus.emit(AgentEvent(event_type="t", agent_name="x"))

        assert len(wb.tracer.get_spans()) == 1  # type: ignore[attr-defined]
        assert len(wb.recent_events) == 1

        wb.reset()

        assert len(wb.tracer.get_spans()) == 0  # type: ignore[attr-defined]
        assert len(wb.recent_events) == 0
        assert len(mem.entries) == 1  # memory survives


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_returns_trace_and_events(self):
        wb = Workbench(memory=_FakeMemory())
        span = wb.tracer.start_span("mesh", agent_name="orchestrator")  # type: ignore[attr-defined]
        wb.tracer.end_span(span, attributes={"note": "plate"})  # type: ignore[attr-defined]
        await wb.event_bus.emit(
            AgentEvent(event_type="plan.init", agent_name="o", data={"tasks": []})
        )

        snap = wb.snapshot()

        assert list(snap.keys()) == ["trace", "events"]
        assert len(snap["trace"]) == 1
        assert snap["trace"][0]["name"] == "mesh"
        assert len(snap["events"]) == 1
        assert snap["events"][0]["event_type"] == "plan.init"

    def test_snapshot_is_json_safe(self):
        wb = Workbench(memory=_FakeMemory())
        snap = wb.snapshot()
        import json

        # Raises if any value isn't JSON-serializable
        json.dumps(snap)
