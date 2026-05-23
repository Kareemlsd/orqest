"""Process-level session runtime cache.

One :class:`SessionRuntime` (Workbench + HookRunner + optional
HealingRunner) per active session. Keyed by the session UUID string.
Tool handlers look up the runtime to emit events on the session's
:class:`~orqest.observability.EventBus`, and the SSE / snapshot endpoints
read from this cache so events flow across turns.

This is an in-process dict, not a distributed cache — fine for the
single-backend localhost demo. Scale-out would swap this for Redis-backed
pub/sub.

:func:`get_runtime` stays sync (lazy construction); the chat router
calls :meth:`SessionRuntime.ensure_started` before the first turn so the
healing poll loop is owned by the request lifetime, not import time.
:func:`drop_runtime` is async because shutting the runner down requires
awaiting the cancelled poll task.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from orqest.observability import AgentEvent

from polymath.workbench_factory import SessionRuntime, build_workbench

_runtimes: dict[str, SessionRuntime] = {}


def get_runtime(session_id: str) -> SessionRuntime:
    """Return (or lazily construct) the :class:`SessionRuntime` for *session_id*.

    Sync on purpose: callers that need the healing poll loop running
    must additionally ``await runtime.ensure_started()``. Most call
    sites (event emit, takeover toggle, snapshot reads) don't need the
    poll loop and treat the runtime as a passive container.
    """
    rt = _runtimes.get(session_id)
    if rt is None:
        rt = build_workbench(session_id)
        _runtimes[session_id] = rt
    return rt


async def drop_runtime(session_id: str) -> None:
    """Evict the runtime for *session_id* and stop its healing poll loop."""
    rt = _runtimes.pop(session_id, None)
    if rt is not None:
        await rt.shutdown()


async def emit(
    session_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Emit an :class:`AgentEvent` on the session's bus."""
    runtime = get_runtime(session_id)
    await runtime.workbench.event_bus.emit(
        AgentEvent(
            event_type=event_type,
            agent_name=f"polymath[{session_id}]",
            timestamp=datetime.now(UTC),
            data=data or {},
        )
    )
