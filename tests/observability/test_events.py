"""Tests for the EventBus and AgentEvent model."""

import pytest

from orqest.observability.events import AgentEvent, EventBus


def _make_event(
    event_type: str = "agent_start",
    agent_name: str = "test-agent",
) -> AgentEvent:
    return AgentEvent(event_type=event_type, agent_name=agent_name)


class TestSubscribeAndEmit:
    """Basic subscribe + emit flow."""

    @pytest.mark.asyncio
    async def test_handler_called_on_matching_event(self) -> None:
        bus = EventBus()
        received: list[AgentEvent] = []
        bus.subscribe("agent_start", received.append)

        event = _make_event("agent_start")
        await bus.emit(event)

        assert received == [event]

    @pytest.mark.asyncio
    async def test_subscribe_all_receives_any_event(self) -> None:
        bus = EventBus()
        received: list[AgentEvent] = []
        bus.subscribe_all(received.append)

        e1 = _make_event("agent_start")
        e2 = _make_event("agent_complete")
        await bus.emit(e1)
        await bus.emit(e2)

        assert received == [e1, e2]

    @pytest.mark.asyncio
    async def test_multiple_handlers_same_type_all_called(self) -> None:
        bus = EventBus()
        r1: list[AgentEvent] = []
        r2: list[AgentEvent] = []
        bus.subscribe("tool_call", r1.append)
        bus.subscribe("tool_call", r2.append)

        event = _make_event("tool_call")
        await bus.emit(event)

        assert r1 == [event]
        assert r2 == [event]


class TestHandlerErrors:
    """Fire-and-forget error semantics."""

    @pytest.mark.asyncio
    async def test_handler_error_logged_not_propagated(self) -> None:
        bus = EventBus()
        logged: list[str] = []

        def bad_handler(event: AgentEvent) -> None:
            raise RuntimeError("boom")

        bus.subscribe("error", bad_handler)

        # Capture loguru output via a custom sink
        from loguru import logger

        handler_id = logger.add(logged.append, format="{message}")
        try:
            # Should not raise
            await bus.emit(_make_event("error"))
        finally:
            logger.remove(handler_id)

        assert any("failed" in msg for msg in logged)


class TestSyncAsyncHandlers:
    """Both sync and async handlers are supported."""

    @pytest.mark.asyncio
    async def test_sync_handler_works(self) -> None:
        bus = EventBus()
        received: list[str] = []

        def sync_h(event: AgentEvent) -> None:
            received.append(event.event_type)

        bus.subscribe("custom", sync_h)
        await bus.emit(_make_event("custom"))

        assert received == ["custom"]

    @pytest.mark.asyncio
    async def test_async_handler_works(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def async_h(event: AgentEvent) -> None:
            received.append(event.event_type)

        bus.subscribe("custom", async_h)
        await bus.emit(_make_event("custom"))

        assert received == ["custom"]


class TestUnsubscribe:
    """Handler removal."""

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self) -> None:
        bus = EventBus()
        received: list[AgentEvent] = []
        bus.subscribe("x", received.append)
        bus.unsubscribe("x", received.append)

        await bus.emit(_make_event("x"))
        assert received == []


class TestEmitNoSubscribers:
    """Emit with no matching handlers."""

    @pytest.mark.asyncio
    async def test_emit_with_no_subscribers_no_error(self) -> None:
        bus = EventBus()
        # Should not raise
        await bus.emit(_make_event("orphan_event"))
