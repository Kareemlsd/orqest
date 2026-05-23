"""``UIEmitter`` — convenience helpers for publishing component events.

Wraps :class:`EventBus` with the SSE-event-type convention from
:mod:`orqest.ui.events`. Mirrors the pattern :class:`ExecutionPlan`
already uses (init payload + delta events) and generalises it across
components.

The emitter does not own the registry — it is just a typing-aware
facade over the bus. Failures emit a debug log; never raised
(best-effort).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from orqest.observability.events import AgentEvent, EventBus
from orqest.ui.events import (
    ui_delta_event_type,
    ui_init_event_type,
    ui_remove_event_type,
)
from orqest.ui.spec import UIComponentSpec, UIDeltaEvent, UIDeltaOp


class UIEmitter:
    """Facade for publishing :class:`UIComponentSpec` and
    :class:`UIDeltaEvent` events on a :class:`EventBus`.
    """

    def __init__(
        self,
        bus: EventBus | None = None,
        *,
        agent_name: str = "ui",
    ) -> None:
        self._bus = bus
        self._agent_name = agent_name

    async def init(
        self,
        component: UIComponentSpec[Any],
        *,
        agent_name: str | None = None,
    ) -> AgentEvent | None:
        """Emit ``ui.<component_type>.init`` for a fresh component.

        Returns the emitted :class:`AgentEvent` for the caller to log /
        record, or ``None`` when no bus is configured. Bus failures
        log at DEBUG and return ``None``.
        """
        event = AgentEvent(
            event_type=ui_init_event_type(component.component_type),
            agent_name=agent_name or self._agent_name,
            data=component.to_event_data(),
        )
        if self._bus is None:
            return event
        try:
            await self._bus.emit(event)
        except Exception as exc:
            logger.debug("UIEmitter.init failed: {e}", e=exc)
            return None
        return event

    async def delta(
        self,
        *,
        component_id: str,
        component_type: str,
        op: UIDeltaOp,
        path: str = "",
        value: Any = None,
        agent_name: str | None = None,
    ) -> AgentEvent | None:
        """Emit ``ui.<component_type>.delta`` with a partial update."""
        delta = UIDeltaEvent(
            component_id=component_id,
            component_type=component_type,
            op=op,
            path=path,
            value=value,
        )
        event = AgentEvent(
            event_type=ui_delta_event_type(component_type),
            agent_name=agent_name or self._agent_name,
            data=delta.to_event_data(),
        )
        if self._bus is None:
            return event
        try:
            await self._bus.emit(event)
        except Exception as exc:
            logger.debug("UIEmitter.delta failed: {e}", e=exc)
            return None
        return event

    async def remove(
        self,
        *,
        component_id: str,
        component_type: str,
        agent_name: str | None = None,
    ) -> AgentEvent | None:
        """Emit ``ui.<component_type>.remove`` so the frontend
        unmounts the component."""
        event = AgentEvent(
            event_type=ui_remove_event_type(component_type),
            agent_name=agent_name or self._agent_name,
            data={"component_id": component_id},
        )
        if self._bus is None:
            return event
        try:
            await self._bus.emit(event)
        except Exception as exc:
            logger.debug("UIEmitter.remove failed: {e}", e=exc)
            return None
        return event
