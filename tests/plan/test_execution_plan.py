"""Tests for ExecutionPlan — schema stability, status updates, event emission."""

from __future__ import annotations

import json

import pytest

from orqest.observability.events import AgentEvent, EventBus
from orqest.plan import ExecutionPlan, PlanSubtask, PlanTask


class _RecordingBus(EventBus):
    """EventBus variant that records emissions for assertion."""

    def __init__(self) -> None:
        super().__init__()
        self.emitted: list[AgentEvent] = []
        self.subscribe_all(self.emitted.append)


@pytest.fixture()
def simple_plan() -> ExecutionPlan:
    return ExecutionPlan(
        tasks=[
            PlanTask(
                id="mesh",
                title="Mesh",
                status="pending",
                priority="required",
                subtasks=[
                    PlanSubtask(id="mesh.geo", title="Write .geo"),
                    PlanSubtask(id="mesh.msh", title="Run Gmsh"),
                ],
            ),
            PlanTask(id="solve", title="Solve", dependencies=["mesh"]),
        ]
    )


class TestSchema:
    def test_to_sse_init_shape_matches_numatics_v2(self, simple_plan):
        """Must emit {"tasks": [PlanTask.model_dump()...]} to stay frontend-compatible."""
        init = simple_plan.to_sse_init()
        assert list(init.keys()) == ["tasks"]
        assert len(init["tasks"]) == 2
        first = init["tasks"][0]
        # fields that the v2 frontend reads
        for required_field in [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "level",
            "dependencies",
            "subtasks",
        ]:
            assert required_field in first
        assert first["id"] == "mesh"
        assert first["subtasks"][0]["id"] == "mesh.geo"

    def test_from_tasks_json_accepts_string(self):
        raw = json.dumps([{"id": "t1", "title": "T1"}])
        plan = ExecutionPlan.from_tasks_json(raw)
        assert len(plan.tasks) == 1
        assert plan.tasks[0].id == "t1"

    def test_from_tasks_json_accepts_wrapped_dict(self):
        plan = ExecutionPlan.from_tasks_json({"tasks": [{"id": "t", "title": "T"}]})
        assert plan.tasks[0].id == "t"

    def test_from_tasks_json_accepts_bare_list(self):
        plan = ExecutionPlan.from_tasks_json([{"id": "t", "title": "T"}])
        assert plan.tasks[0].id == "t"


class TestStatusUpdates:
    @pytest.mark.asyncio
    async def test_set_task_status_updates_in_place(self, simple_plan):
        await simple_plan.set_task_status("mesh", "in-progress")
        assert simple_plan.tasks[0].status == "in-progress"

    @pytest.mark.asyncio
    async def test_set_subtask_status(self, simple_plan):
        payload = await simple_plan.set_task_status(
            "mesh", "completed", subtask_id="mesh.geo"
        )
        assert simple_plan.tasks[0].subtasks[0].status == "completed"
        assert payload == {
            "task_id": "mesh",
            "status": "completed",
            "subtask_id": "mesh.geo",
        }
        # Parent task untouched
        assert simple_plan.tasks[0].status == "pending"

    @pytest.mark.asyncio
    async def test_returns_payload_matching_v2_contract(self, simple_plan):
        """Frontend expects exactly {task_id, status, [subtask_id]}."""
        task_only = await simple_plan.set_task_status("mesh", "completed")
        assert task_only == {"task_id": "mesh", "status": "completed"}

    @pytest.mark.asyncio
    async def test_missing_task_silently_ignored(self, simple_plan):
        # Should not raise — matches v2 PlanContext.update_task behavior
        payload = await simple_plan.set_task_status("doesnotexist", "completed")
        assert payload["task_id"] == "doesnotexist"


class TestEventEmission:
    @pytest.mark.asyncio
    async def test_set_task_status_emits_on_bus(self, simple_plan):
        bus = _RecordingBus()
        await simple_plan.set_task_status(
            "mesh", "completed", bus=bus, agent_name="orchestrator"
        )
        assert len(bus.emitted) == 1
        ev = bus.emitted[0]
        assert ev.event_type == "plan.task.updated"
        assert ev.agent_name == "orchestrator"
        assert ev.data == {"task_id": "mesh", "status": "completed"}

    @pytest.mark.asyncio
    async def test_emit_init_publishes_full_plan(self, simple_plan):
        bus = _RecordingBus()
        payload = await simple_plan.emit_init(bus, agent_name="o")
        assert payload == simple_plan.to_sse_init()
        assert len(bus.emitted) == 1
        assert bus.emitted[0].event_type == "plan.init"
        assert bus.emitted[0].data == payload

    @pytest.mark.asyncio
    async def test_no_bus_means_no_emission(self, simple_plan):
        """Passing bus=None skips emission without erroring."""
        await simple_plan.set_task_status("mesh", "completed")  # no bus
        # No exceptions, no state corruption
        assert simple_plan.tasks[0].status == "completed"


class TestV2Parity:
    """Behavior parity with numatics-ai v2's PlanContext.update_task."""

    @pytest.mark.asyncio
    async def test_sse_init_shape_matches_v2_fixture(self):
        """Regression test — the v6 schema fixture the frontend was built on."""
        plan = ExecutionPlan.from_tasks_json([
            {
                "id": "mesh",
                "title": "Generate geometry & mesh",
                "status": "pending",
                "priority": "required",
                "level": 0,
                "dependencies": [],
                "subtasks": [
                    {
                        "id": "mesh.geo",
                        "title": "Write .geo script",
                        "status": "pending",
                        "priority": "required",
                    }
                ],
            },
        ])

        init = plan.to_sse_init()
        assert init == {
            "tasks": [
                {
                    "id": "mesh",
                    "title": "Generate geometry & mesh",
                    "description": "",
                    "status": "pending",
                    "priority": "required",
                    "level": 0,
                    "dependencies": [],
                    "subtasks": [
                        {
                            "id": "mesh.geo",
                            "title": "Write .geo script",
                            "description": "",
                            "status": "pending",
                            "priority": "required",
                            "tools": [],
                        }
                    ],
                }
            ]
        }
