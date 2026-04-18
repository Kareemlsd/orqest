"""Workbench FastAPI router — chat + sidecar endpoints for memory/trace/events."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from demo.backend.workbench.agent import agent, start_agent_run_span
from demo.backend.workbench.state import (
    forget_memory,
    reset_session,
    snapshot_events,
    snapshot_memories,
    snapshot_trace,
)

router = APIRouter(prefix="/api/workbench")


@router.post("/chat")
async def chat(request: Request) -> Response:
    """Stream the workbench agent via the Vercel AI Data Stream Protocol.

    Tool calls, text deltas, and the agent's structured tool emissions
    (emit_plan, emit_artifact, remember, recall) all stream naturally
    through the adapter. The frontend demultiplexes them into the
    contextual panels.

    Traces are opened here and closed via the ``on_complete`` callback —
    this way the span's ``duration_ms`` reflects the full streaming run,
    not just the time to return the StreamingResponse.
    """
    _, finalize = start_agent_run_span()

    async def on_complete(result):  # type: ignore[no-untyped-def]
        finalize(status="ok")

    return await VercelAIAdapter.dispatch_request(
        request, agent=agent, on_complete=on_complete
    )


@router.get("/state")
async def state_snapshot() -> dict:
    """Snapshot of memory + trace + events for the sidecar panels.

    The frontend polls this every ~1s during streaming to update the
    Memory, Trace, and Events tabs. A production app would use SSE or
    WebSockets for real-time; polling keeps this demo dependency-free.
    """
    return {
        "memories": await snapshot_memories(),
        "trace": snapshot_trace(),
        "events": snapshot_events(),
    }


@router.post("/memory/forget")
async def memory_forget(body: dict) -> dict:
    """Delete a single memory by id."""
    entry_id = body.get("id", "")
    if not entry_id:
        return {"error": "id required"}
    await forget_memory(entry_id)
    return {"ok": True, "id": entry_id}


@router.post("/reset")
async def reset() -> dict:
    """Clear tracer + event buffer for a fresh session. Memory persists."""
    reset_session()
    return {"ok": True}
