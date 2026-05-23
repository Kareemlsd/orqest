"""Workbench snapshot endpoint — trace + recent events JSON."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from polymath.runtime import get_runtime

router = APIRouter(prefix="/sessions", tags=["snapshot"])


@router.get("/{sid}/snapshot")
async def get_snapshot(sid: UUID) -> dict:
    """Return ``workbench.snapshot()`` for *sid* — trace + events ring buffer."""
    runtime = get_runtime(str(sid))
    return runtime.workbench.snapshot()


@router.get("/{sid}/plan")
async def get_plan(sid: UUID) -> dict:
    """Return the session's current :class:`ExecutionPlan` in SSE-init shape.

    This is what the frontend's ``PlanHeader`` reads on mount. Once a plan
    is initialised via the agent's ``init_plan`` tool, it stays on
    ``PolymathState`` which the agent receives via ``deps`` every turn.
    The endpoint re-reads from the latest persisted plan if present;
    Phase 1 keeps it memory-only and returns an empty plan if the agent
    has not called ``init_plan`` yet in this process.
    """
    runtime = get_runtime(str(sid))
    # The plan itself is owned by PolymathState which is built per-request.
    # For a simple read endpoint, we derive the latest plan from the event
    # ring buffer: find the most recent `plan.init` + apply any subsequent
    # `plan.task.updated` mutations. This keeps the plan surface coherent
    # across reconnects without persisting it to the DB in Phase 1.
    tasks_init: list[dict] = []
    for event in runtime.workbench.recent_events:
        if event.event_type == "plan.init":
            tasks_init = list(event.data.get("tasks") or [])
        elif event.event_type == "plan.task.updated" and tasks_init:
            tid = event.data.get("task_id")
            new_status = event.data.get("status")
            subtask_id = event.data.get("subtask_id")
            for t in tasks_init:
                if t.get("id") != tid:
                    continue
                if subtask_id:
                    for s in t.get("subtasks", []):
                        if s.get("id") == subtask_id:
                            s["status"] = new_status
                else:
                    t["status"] = new_status
                break
    return {"tasks": tasks_init}
