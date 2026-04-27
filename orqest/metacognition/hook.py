"""``MetacognitionHook`` — bridges :class:`EnrichedOutput` to :class:`EventBus`.

A :class:`ToolHook` that publishes ``metacognition.confidence`` events
when a tool result is an :class:`EnrichedOutput`. Returns ``None`` from
all methods, so :class:`HookRunner` auto-wraps to :class:`Continue` —
the hook is a pure observer.
"""

from __future__ import annotations

from typing import Any

from orqest.metacognition.enriched import EnrichedOutput
from orqest.observability.events import AgentEvent, EventBus


def _state_meta(state: Any) -> dict[str, Any]:
    """Extract ``session_id`` / ``project_id`` from state if present."""
    meta: dict[str, Any] = {}
    sid = getattr(state, "session_id", None)
    if sid is not None:
        meta["session_id"] = sid
    pid = getattr(state, "project_id", None)
    if pid is not None:
        meta["project_id"] = pid
    return meta


class MetacognitionHook:
    """ToolHook that publishes enriched-output telemetry to an EventBus.

    Implements only ``after_tool``: when the tool result is an
    :class:`EnrichedOutput`, emits one ``metacognition.confidence``
    AgentEvent. Other tool results are ignored (best-effort: safe to
    register on any HookRunner, even in agents that don't use enrichment).

    The hook returns ``None`` to honor the existing observation-only
    contract — :class:`HookRunner` auto-wraps to :class:`Continue`.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        agent_name: str = "unknown",
    ) -> None:
        self._bus = bus
        self._agent_name = agent_name

    async def after_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        state: Any,
        duration_ms: float,
    ) -> None:
        if not isinstance(result, EnrichedOutput):
            return
        await self._bus.emit(
            AgentEvent(
                event_type="metacognition.confidence",
                agent_name=self._agent_name,
                data={
                    "tool_name": tool_name,
                    "confidence": result.confidence,
                    "capability_boundary": result.capability_boundary,
                    "uncertainty_targets": list(result.uncertainty_targets),
                    "protocol": result.protocol_name,
                    "duration_ms": round(duration_ms, 2),
                    **_state_meta(state),
                },
            )
        )
