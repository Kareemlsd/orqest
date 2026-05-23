"""Tests for MetacognitionHook."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from orqest.hooks import HookRunner
from orqest.metacognition import EnrichedOutput, MetacognitionHook
from orqest.observability.events import EventBus


class _Out(BaseModel):
    answer: str


class _RecordingBus(EventBus):
    """EventBus that records every emit for inspection."""

    def __init__(self) -> None:
        super().__init__()
        self.recorded: list = []

    async def emit(self, event):
        self.recorded.append(event)
        await super().emit(event)


@pytest.mark.asyncio
async def test_hook_emits_metacognition_event_for_enriched_output():
    bus = _RecordingBus()
    hook = MetacognitionHook(bus, agent_name="test_agent")

    enriched = EnrichedOutput(
        output=_Out(answer="42"),
        confidence=0.85,
        uncertainty_targets=["assumption_X"],
        capability_boundary=False,
        protocol_name="structured",
    )

    await hook.after_tool("my_tool", {}, enriched, None, 100.0)

    assert len(bus.recorded) == 1
    evt = bus.recorded[0]
    assert evt.event_type == "metacognition.confidence"
    assert evt.agent_name == "test_agent"
    assert evt.data["tool_name"] == "my_tool"
    assert evt.data["confidence"] == 0.85
    assert evt.data["uncertainty_targets"] == ["assumption_X"]
    assert evt.data["capability_boundary"] is False
    assert evt.data["protocol"] == "structured"
    assert evt.data["duration_ms"] == 100.0


@pytest.mark.asyncio
async def test_hook_skips_non_enriched_output():
    bus = _RecordingBus()
    hook = MetacognitionHook(bus)

    await hook.after_tool("my_tool", {}, "raw-string-result", None, 5.0)

    assert bus.recorded == []


@pytest.mark.asyncio
async def test_hook_extracts_session_id_from_state():
    class _State:
        session_id = "sess-42"
        project_id = "proj-1"

    bus = _RecordingBus()
    hook = MetacognitionHook(bus)
    enriched = EnrichedOutput(output=_Out(answer="x"), confidence=0.5)

    await hook.after_tool("my_tool", {}, enriched, _State(), 10.0)

    evt = bus.recorded[0]
    assert evt.data["session_id"] == "sess-42"
    assert evt.data["project_id"] == "proj-1"


@pytest.mark.asyncio
async def test_hook_works_through_hook_runner():
    """MetacognitionHook returns None; HookRunner auto-wraps to Continue."""
    from orqest.hooks import Continue

    bus = _RecordingBus()
    runner = HookRunner([MetacognitionHook(bus)])
    enriched = EnrichedOutput(output=_Out(answer="x"), confidence=0.5)

    decision = await runner.run_after("t", {}, enriched, None, 1.0)
    assert isinstance(decision, Continue)
    assert len(bus.recorded) == 1
