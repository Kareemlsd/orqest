"""In-process event bus for agent observability.

Provides AgentEvent — a lightweight event emitted during agent execution —
and EventBus — a pub/sub dispatcher that supports both sync and async handlers.
Handler errors are logged at WARNING level and never propagated, matching the
fire-and-forget pattern established by HookRunner.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from loguru import logger

EventHandler = (
    Callable[["AgentEvent"], Awaitable[None]]
    | Callable[["AgentEvent"], None]
)


@dataclass(frozen=True)
class AgentEvent:
    """Event emitted during agent execution.

    Carries the event type, originating agent, and an arbitrary data payload.
    Optionally linked to a trace span for correlation.
    """

    event_type: str
    agent_name: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    data: dict[str, Any] = field(default_factory=dict)
    span_id: str | None = None
    trace_id: str | None = None


class EventBus:
    """In-process pub/sub for AgentEvents.

    Fire-and-forget: handler errors are logged at WARNING level and never
    re-raised, so a broken handler cannot disrupt agent execution.
    Supports both sync and async handlers.
    """

    def __init__(self) -> None:
        """Initialize with empty handler registries."""
        self._handlers: dict[str, list[EventHandler]] = {}
        self._global_handlers: list[EventHandler] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler that receives every event regardless of type."""
        self._global_handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler for a specific event type.

        Silently ignores handlers that are not registered.
        """
        handlers = self._handlers.get(event_type)
        if handlers is None:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Remove a handler registered via :meth:`subscribe_all`.

        Silently ignores handlers that are not registered.
        """
        try:
            self._global_handlers.remove(handler)
        except ValueError:
            pass

    async def emit(self, event: AgentEvent) -> None:
        """Dispatch an event to all matching handlers.

        Calls type-specific handlers first, then global handlers.
        Each handler is invoked independently — a failure in one does not
        prevent others from running.
        """
        targets = list(self._handlers.get(event.event_type, []))
        targets.extend(self._global_handlers)
        for handler in targets:
            await self._safe_call(handler, event)

    async def _safe_call(self, handler: EventHandler, event: AgentEvent) -> None:
        """Invoke a handler, swallowing any exception."""
        try:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning(
                "EventBus handler {handler} failed for {event_type}",
                handler=getattr(handler, "__name__", repr(handler)),
                event_type=event.event_type,
            )
