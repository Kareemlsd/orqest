"""Tests for plan reconstruction from the event ring buffer."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from orqest.observability import AgentEvent


@pytest.mark.asyncio
async def test_plan_empty_for_fresh_session(client: AsyncClient) -> None:
    """New session has an empty plan (no init event yet)."""
    sid = (await client.post("/sessions")).json()["id"]
    r = await client.get(f"/sessions/{sid}/plan")
    assert r.status_code == 200
    assert r.json() == {"tasks": []}


@pytest.mark.asyncio
async def test_plan_reflects_init_event(client: AsyncClient) -> None:
    """After a plan.init event, GET /plan returns those tasks."""
    from polymath import runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = runtime.get_runtime(sid)
    await rt.workbench.event_bus.emit(
        AgentEvent(
            event_type="plan.init",
            agent_name="test",
            data={
                "tasks": [
                    {"id": "t1", "title": "One", "status": "pending"},
                    {"id": "t2", "title": "Two", "status": "pending"},
                ]
            },
        )
    )
    r = await client.get(f"/sessions/{sid}/plan")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tasks"]) == 2
    assert [t["id"] for t in body["tasks"]] == ["t1", "t2"]
    assert all(t["status"] == "pending" for t in body["tasks"])


@pytest.mark.asyncio
async def test_plan_applies_subsequent_updates(client: AsyncClient) -> None:
    """plan.task.updated events mutate the reconstructed plan in place."""
    from polymath import runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = runtime.get_runtime(sid)
    bus = rt.workbench.event_bus

    await bus.emit(
        AgentEvent(
            event_type="plan.init",
            agent_name="test",
            data={
                "tasks": [
                    {"id": "a", "title": "A", "status": "pending"},
                    {"id": "b", "title": "B", "status": "pending"},
                ]
            },
        )
    )
    await bus.emit(
        AgentEvent(
            event_type="plan.task.updated",
            agent_name="test",
            data={"task_id": "a", "status": "in-progress"},
        )
    )
    await bus.emit(
        AgentEvent(
            event_type="plan.task.updated",
            agent_name="test",
            data={"task_id": "a", "status": "completed"},
        )
    )

    r = await client.get(f"/sessions/{sid}/plan")
    tasks = {t["id"]: t["status"] for t in r.json()["tasks"]}
    assert tasks == {"a": "completed", "b": "pending"}


@pytest.mark.asyncio
async def test_plan_update_ignored_before_init(client: AsyncClient) -> None:
    """A bare plan.task.updated without a prior plan.init is a no-op."""
    from polymath import runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = runtime.get_runtime(sid)
    await rt.workbench.event_bus.emit(
        AgentEvent(
            event_type="plan.task.updated",
            agent_name="test",
            data={"task_id": "orphan", "status": "completed"},
        )
    )
    r = await client.get(f"/sessions/{sid}/plan")
    assert r.json() == {"tasks": []}


@pytest.mark.asyncio
async def test_plan_subtask_update(client: AsyncClient) -> None:
    """Nested subtask status updates target only the matching subtask."""
    from polymath import runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = runtime.get_runtime(sid)
    bus = rt.workbench.event_bus

    await bus.emit(
        AgentEvent(
            event_type="plan.init",
            agent_name="test",
            data={
                "tasks": [
                    {
                        "id": "top",
                        "title": "Top",
                        "status": "in-progress",
                        "subtasks": [
                            {"id": "s1", "title": "s1", "status": "pending"},
                            {"id": "s2", "title": "s2", "status": "pending"},
                        ],
                    }
                ]
            },
        )
    )
    await bus.emit(
        AgentEvent(
            event_type="plan.task.updated",
            agent_name="test",
            data={"task_id": "top", "subtask_id": "s2", "status": "completed"},
        )
    )

    body = (await client.get(f"/sessions/{sid}/plan")).json()
    sub_statuses = {s["id"]: s["status"] for s in body["tasks"][0]["subtasks"]}
    assert sub_statuses == {"s1": "pending", "s2": "completed"}
