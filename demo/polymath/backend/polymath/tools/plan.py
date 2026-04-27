"""Plan tools — the agent emits its todo list through these.

Every run should begin with :func:`init_plan` announcing the task tree.
As work progresses the agent calls :func:`update_plan` on each task to
flip status; each update emits a ``plan.task.updated`` event so the
frontend's ``PlanHeader`` can tick checkboxes in real time.

Reference: ``docs/concepts/execution-plan.md``.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel
from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from orqest.plan import ExecutionPlan, PlanStatus, PlanSubtask, PlanTask

from polymath.runtime import emit, get_runtime
from polymath.state import PolymathState


class _SubtaskIn(BaseModel):
    id: str
    title: str
    description: str = ""
    tools: list[str] = []


class _TaskIn(BaseModel):
    id: str
    title: str
    description: str = ""
    priority: Literal["required", "optional"] = "required"
    subtasks: list[_SubtaskIn] = []


async def _init_plan(
    ctx: RunContext[PolymathState],
    tasks: Annotated[
        list[_TaskIn],
        "Ordered list of tasks. Each task has id, title, optional description/subtasks.",
    ],
) -> str:
    """Publish the session's top-level plan. Call this first, before any tool work."""
    plan = ExecutionPlan(
        tasks=[
            PlanTask(
                id=t.id,
                title=t.title,
                description=t.description,
                priority=t.priority,
                subtasks=[
                    PlanSubtask(
                        id=s.id,
                        title=s.title,
                        description=s.description,
                        tools=s.tools,
                    )
                    for s in t.subtasks
                ],
            )
            for t in tasks
        ]
    )
    # Phase β: opt into the typed ``ui.plan.{init,delta}`` channel
    # alongside the legacy ``plan.init`` / ``plan.task.updated`` events.
    # The flag is off by default in Orqest core to preserve byte-stable
    # emission counts; Polymath wants the dual-emission so the frontend
    # can migrate to the generative-UI listener whitelist.
    plan.enable_ui_events(component_id="plan")
    ctx.deps.plan = plan
    bus = get_runtime(ctx.deps.session_id).workbench.event_bus
    await plan.emit_init(bus, agent_name=f"polymath[{ctx.deps.session_id}]")
    return json.dumps({"tasks": [t.id for t in plan.tasks]})


async def _update_plan(
    ctx: RunContext[PolymathState],
    task_id: Annotated[str, "ID of the task whose status should change."],
    status: Annotated[
        PlanStatus,
        "New status: pending | in-progress | completed | failed | skipped.",
    ],
    subtask_id: Annotated[
        str | None,
        "If provided, update the nested subtask rather than the parent task.",
    ] = None,
) -> str:
    """Flip a plan task's status and broadcast the change."""
    if ctx.deps.plan is None:
        await emit(
            ctx.deps.session_id,
            "plan.update.ignored",
            {"reason": "no plan initialised", "task_id": task_id},
        )
        return json.dumps({"error": "no plan initialised — call init_plan first"})

    bus = get_runtime(ctx.deps.session_id).workbench.event_bus
    change = await ctx.deps.plan.set_task_status(
        task_id,
        status,
        subtask_id=subtask_id,
        bus=bus,
        agent_name=f"polymath[{ctx.deps.session_id}]",
    )
    return json.dumps(change)


init_plan = Tool(_init_plan, name="init_plan")
update_plan = Tool(_update_plan, name="update_plan")
