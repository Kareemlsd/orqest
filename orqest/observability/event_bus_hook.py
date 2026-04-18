"""Hook that auto-publishes tool lifecycle events to an :class:`EventBus`.

``EventBusPublishHook`` bridges :class:`~orqest.hooks.HookRunner` (pre/post
lifecycle for tool execution) and :class:`~orqest.observability.EventBus`
(fan-out pub/sub). Registering the hook on a ``HookRunner`` makes every
compound-tool call observable by any subscriber without repeating the
same ``event_bus.emit(...)`` boilerplate in every consumer.

Events emitted:

* ``tool.before`` — fired on ``before_tool``; ``data`` carries ``tool_name``
  and ``args``.
* ``tool.after`` — fired on ``after_tool``; ``data`` carries ``tool_name``,
  ``duration_ms`` and a truncated ``result_preview``.
* ``tool.error`` — fired on ``on_error``; ``data`` carries ``tool_name``,
  ``error_type`` and ``error_message``.

All three events include the source agent name plus any ``session_id`` /
``project_id`` attributes the hook can read off the state object (via
``getattr`` so non-numatics consumers aren't required to use those
field names).
"""

from __future__ import annotations

from typing import Any

from orqest.observability.events import AgentEvent, EventBus

_RESULT_PREVIEW_CHARS = 400


class EventBusPublishHook:
    """Publish tool lifecycle to an :class:`EventBus`.

    Structural ``ToolHook`` — implements ``before_tool``, ``after_tool``,
    and ``on_error``, so it satisfies
    :class:`orqest.hooks.ToolHook` without inheriting from the Protocol.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        agent_name: str = "unknown",
        result_preview_chars: int = _RESULT_PREVIEW_CHARS,
    ) -> None:
        """Wire the hook to *bus* and tag every published event with
        ``agent_name``.

        Args:
            bus: The :class:`EventBus` to publish to.
            agent_name: Value used as ``AgentEvent.agent_name`` on every
                emitted event. Consumers usually pass the owning
                orchestrator's name.
            result_preview_chars: Max characters from tool results
                included in ``tool.after`` payloads. Long results are
                truncated to keep event payloads bounded.
        """
        self._bus = bus
        self._agent_name = agent_name
        self._result_preview_chars = result_preview_chars

    async def before_tool(
        self, tool_name: str, args: dict[str, Any], state: Any
    ) -> None:
        """Publish ``tool.before`` to the bus."""
        await self._bus.emit(
            AgentEvent(
                event_type="tool.before",
                agent_name=self._agent_name,
                data={
                    "tool_name": tool_name,
                    "args": _summarize_args(args),
                    **_state_meta(state),
                },
            )
        )

    async def after_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
        state: Any,
        duration_ms: float,
    ) -> None:
        """Publish ``tool.after`` to the bus."""
        preview = _truncate(result, self._result_preview_chars)
        await self._bus.emit(
            AgentEvent(
                event_type="tool.after",
                agent_name=self._agent_name,
                data={
                    "tool_name": tool_name,
                    "duration_ms": round(duration_ms, 2),
                    "result_preview": preview,
                    "result_len": len(str(result)) if result is not None else 0,
                    **_state_meta(state),
                },
            )
        )

    async def on_error(
        self,
        tool_name: str,
        args: dict[str, Any],
        error: Exception,
        state: Any,
    ) -> None:
        """Publish ``tool.error`` to the bus."""
        await self._bus.emit(
            AgentEvent(
                event_type="tool.error",
                agent_name=self._agent_name,
                data={
                    "tool_name": tool_name,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    **_state_meta(state),
                },
            )
        )


def _summarize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with oversized values stringified + truncated."""
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v if not isinstance(v, str) or len(v) <= 120 else v[:120] + "..."
        else:
            text = repr(v)
            out[k] = text if len(text) <= 120 else text[:120] + "..."
    return out


def _truncate(result: Any, n: int) -> str:
    """Stringify *result* and truncate to *n* characters with ellipsis."""
    if result is None:
        return ""
    text = str(result)
    return text if len(text) <= n else text[:n] + "..."


def _state_meta(state: Any) -> dict[str, Any]:
    """Best-effort read of session/project identifiers off *state*."""
    meta: dict[str, Any] = {}
    session_id = getattr(state, "session_id", None)
    if session_id:
        meta["session_id"] = session_id
    project_id = getattr(state, "project_id", None)
    if project_id:
        meta["project_id"] = project_id
    return meta
