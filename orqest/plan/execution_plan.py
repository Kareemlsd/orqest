"""Typed execution plan with :class:`EventBus` integration.

Many Orqest agents decompose a user request into a small set of tasks
(mesh → solve → analyze, research → synthesize → respond, …) and want
to track per-task progress visibly. ``ExecutionPlan`` captures that
pattern as a reusable primitive: a Pydantic model of
:class:`PlanTask`\\s with typed statuses, a method to flip a task's
status that also emits a typed :class:`AgentEvent` on a bus, and a
stable ``to_sse_init`` shape the frontend can rely on.

The model is intentionally thin — just enough to carry structure —
because every domain has its own idea of what a "task" means.
Consumers compose tasks externally (often by asking an LLM to produce
JSON matching the schema) and hand the plan to ``ExecutionPlan``.

Schema contract (must remain stable):

* ``to_sse_init()`` returns ``{"tasks": [PlanTask.model_dump()...]}``.
* ``set_task_status`` returns the exact payload that the frontend
  expects on a task-update event: ``{"task_id": ..., "status": ...}``
  plus ``"subtask_id": ...`` when updating a subtask.

This contract is duplicated in the consumer's SSE adapter — changing it
silently breaks the frontend.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.observability.events import AgentEvent, EventBus

PlanStatus = Literal[
    "pending", "in-progress", "completed", "failed", "skipped",
]
"""Task status values understood by the frontend plan UI."""


class PlanSubtask(BaseModel):
    """A subtask nested under a :class:`PlanTask`."""

    id: str
    title: str
    description: str = ""
    status: PlanStatus = "pending"
    priority: Literal["required", "optional"] = "required"
    tools: list[str] = Field(default_factory=list)


class PlanTask(BaseModel):
    """A top-level task in an :class:`ExecutionPlan`."""

    id: str
    title: str
    description: str = ""
    status: PlanStatus = "pending"
    priority: Literal["required", "optional"] = "required"
    level: int = 0
    dependencies: list[str] = Field(default_factory=list)
    subtasks: list[PlanSubtask] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """Ordered list of tasks + helpers to emit status updates.

    Tasks are mutable: ``set_task_status`` rewrites a task (or subtask)
    in place and returns the payload the consumer should forward to the
    frontend. When an ``EventBus`` is attached, the same payload is also
    emitted as an :class:`AgentEvent` so any subscriber (e.g. the SSE
    sidecar) can observe the change.
    """

    tasks: list[PlanTask] = Field(default_factory=list)

    # Not serialized — the bus is a runtime detail, not part of the schema.
    model_config = {"arbitrary_types_allowed": True}

    def to_sse_init(self) -> dict[str, Any]:
        """Return the ``plan.init`` payload the frontend expects."""
        return {"tasks": [t.model_dump() for t in self.tasks]}

    async def set_task_status(
        self,
        task_id: str,
        status: PlanStatus,
        *,
        subtask_id: str | None = None,
        bus: EventBus | None = None,
        agent_name: str = "unknown",
    ) -> dict[str, Any]:
        """Flip a task (or subtask) status and return the update payload.

        Args:
            task_id: ID of the :class:`PlanTask` to update.
            status: New status value.
            subtask_id: If provided, update the matching subtask rather
                than the parent task.
            bus: Optional :class:`EventBus` to publish a
                ``plan.task.updated`` event to. Omit for tests or
                in-memory-only usage.
            agent_name: Tagged on emitted events for source attribution.

        Returns:
            A dict carrying ``task_id`` + ``status`` (and
            ``subtask_id`` if applicable). This is the exact shape the
            consumer forwards to the frontend, so it must remain stable.
        """
        for task in self.tasks:
            if task.id != task_id:
                continue
            if subtask_id is not None:
                for subtask in task.subtasks:
                    if subtask.id == subtask_id:
                        subtask.status = status
                        break
            else:
                task.status = status
            break

        payload: dict[str, Any] = {"task_id": task_id, "status": status}
        if subtask_id is not None:
            payload["subtask_id"] = subtask_id

        if bus is not None:
            await bus.emit(
                AgentEvent(
                    event_type="plan.task.updated",
                    agent_name=agent_name,
                    data=payload,
                )
            )
        return payload

    async def emit_init(
        self,
        bus: EventBus,
        *,
        agent_name: str = "unknown",
    ) -> dict[str, Any]:
        """Publish the initial plan to *bus* as a ``plan.init`` event.

        Convenience for consumers that always want the plan mirrored to
        the bus right after construction. Returns the same payload as
        :meth:`to_sse_init` so the caller can also stream it inline.
        """
        payload = self.to_sse_init()
        await bus.emit(
            AgentEvent(
                event_type="plan.init",
                agent_name=agent_name,
                data=payload,
            )
        )
        return payload

    @classmethod
    def from_tasks_json(
        cls, tasks_json: str | list[dict[str, Any]] | dict[str, Any]
    ) -> "ExecutionPlan":
        """Construct from either a JSON string, a bare task list, or a
        ``{"tasks": [...]}`` dict. Useful when an LLM produces the plan
        as an opaque JSON string.
        """
        import json as _json

        if isinstance(tasks_json, str):
            data = _json.loads(tasks_json)
        else:
            data = tasks_json

        tasks = data if isinstance(data, list) else data.get("tasks", [])
        return cls.model_validate({"tasks": tasks})
