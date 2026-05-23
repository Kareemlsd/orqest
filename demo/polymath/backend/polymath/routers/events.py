"""SSE sidecar stream — serves the session's live event bus.

The frontend's ``useSidecar`` hook opens an ``EventSource`` on this endpoint
and listens for :class:`~orqest.observability.AgentEvent` JSON payloads as
SSE messages. :func:`~orqest.observability.sse_sidecar` handles the protocol
format, heartbeats, replay buffer, and ring-buffered queue against slow
consumers.

Reconnecting clients include the last 200 events from
``workbench.recent_events`` as a replay burst so the UI state catches up
after a browser refresh.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from orqest.observability import sse_sidecar

from polymath.runtime import get_runtime

router = APIRouter(prefix="/sessions", tags=["events"])


@router.get("/{sid}/events")
async def stream_events(sid: UUID) -> StreamingResponse:
    """Stream SSE events for *sid*. Live bus + replay of recent events."""
    runtime = get_runtime(str(sid))
    wb = runtime.workbench
    replay = list(wb.recent_events)
    return StreamingResponse(
        sse_sidecar(wb.event_bus, replay=replay, heartbeat_s=15.0),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
