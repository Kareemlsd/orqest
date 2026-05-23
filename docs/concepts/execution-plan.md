# ExecutionPlan — typed multi-step workflow tracking

When an agent decomposes a user request into discrete steps (mesh →
solve → analyze, research → synthesize → respond, …), the consumer
usually wants to visualize progress: a task list in the UI with per-
task status updates streaming in as work happens. Before
`ExecutionPlan`, every consumer maintained its own Pydantic model,
its own status-flip method, and its own hand-rolled `EventBus` glue
to notify the frontend.

`ExecutionPlan` is the canonical primitive. It wraps a list of
`PlanTask`s (optionally with `PlanSubtask`s), exposes a single
`set_task_status()` that flips state and emits a typed
`plan.task.updated` event, and keeps `to_sse_init()` byte-stable for
frontend compatibility across Orqest releases.

## Minimal example

```python
import asyncio

from orqest import ExecutionPlan, PlanTask, PlanSubtask
from orqest.observability import EventBus


async def main() -> None:
    plan = ExecutionPlan(
        tasks=[
            PlanTask(
                id="mesh",
                title="Generate mesh",
                subtasks=[PlanSubtask(id="mesh.geo", title="Write .geo")],
            ),
            PlanTask(id="solve", title="Run solver", dependencies=["mesh"]),
        ]
    )

    bus = EventBus()
    bus.subscribe_all(lambda e: print(f"{e.event_type}: {e.data}"))

    # Initial payload the frontend renders once
    await plan.emit_init(bus, agent_name="orchestrator")

    # Later — flip a subtask as work starts and completes
    await plan.set_task_status(
        "mesh", "in-progress", subtask_id="mesh.geo", bus=bus,
        agent_name="orchestrator",
    )
    await plan.set_task_status(
        "mesh", "completed", subtask_id="mesh.geo", bus=bus,
        agent_name="orchestrator",
    )


asyncio.run(main())
```

## Schema contract

Two payload shapes are **stable** — frontend code depends on them:

`to_sse_init()` → `{"tasks": [...]}` where each task has `id`,
`title`, `description`, `status`, `priority`, `level`,
`dependencies`, `subtasks`.

`set_task_status()` return value → `{"task_id": ..., "status": ...}`
plus `"subtask_id": ...` when updating a subtask. The same shape lands
on the `EventBus` as the `data` payload of `plan.task.updated` events.

## Statuses

`PlanStatus` = `"pending" | "in-progress" | "completed" | "failed" |
"skipped"`. No additional values are introduced without a frontend
coordination change.

## When to reach for this

- You want a typed plan model instead of a handful of dict
  utilities.
- You want plan updates to flow onto your existing `EventBus`
  subscribers (metrics, SSE sidecar, logging) without extra wiring.
- You want a consistent wire format across multiple Orqest consumers
  so their frontends can share rendering code.

## Reference

::: orqest.plan.ExecutionPlan
::: orqest.plan.PlanTask
::: orqest.plan.PlanSubtask
