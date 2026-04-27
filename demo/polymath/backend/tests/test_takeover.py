"""Takeover endpoints + hook-level Skip behaviour."""

from __future__ import annotations

from uuid import uuid4

import pytest

from polymath import runtime as runtime_mod
from polymath.db.models import Session
from polymath.db.session import get_sessionmaker
from polymath.workbench_factory import TakeoverGate


async def _make_session():
    sm = get_sessionmaker()
    sid = uuid4()
    async with sm() as db:
        db.add(Session(id=sid, title="t"))
        await db.commit()
    return sid


@pytest.mark.asyncio
async def test_takeover_default_inactive(client) -> None:
    sid = await _make_session()
    resp = await client.get(f"/sessions/{sid}/takeover")
    assert resp.status_code == 200
    assert resp.json() == {"active": False}


@pytest.mark.asyncio
async def test_takeover_activate_release_roundtrip(client) -> None:
    sid = await _make_session()

    activated = await client.post(f"/sessions/{sid}/takeover")
    assert activated.status_code == 200
    assert activated.json() == {"active": True}
    assert runtime_mod.get_runtime(str(sid)).takeover_active is True

    released = await client.post(f"/sessions/{sid}/resume")
    assert released.status_code == 200
    assert released.json() == {"active": False}
    assert runtime_mod.get_runtime(str(sid)).takeover_active is False


@pytest.mark.asyncio
async def test_takeover_emits_events(client) -> None:
    sid = await _make_session()
    rt = runtime_mod.get_runtime(str(sid))
    seen: list[str] = []

    async def handler(evt) -> None:
        seen.append(evt.event_type)

    rt.workbench.event_bus.subscribe_all(handler)

    await client.post(f"/sessions/{sid}/takeover")
    await client.post(f"/sessions/{sid}/resume")
    assert "takeover.activated" in seen
    assert "takeover.released" in seen


@pytest.mark.asyncio
async def test_takeover_gate_skips_tool_calls_via_hook_runner() -> None:
    """While takeover is active, the HookRunner aggregates a Skip from
    :class:`TakeoverGate` so the compound-flow boundary returns the
    stub_result instead of executing the tool."""
    from orqest.hooks import Skip

    sid = "gate-skip-sid"
    rt = runtime_mod.get_runtime(sid)
    rt.takeover_active = True

    decision = await rt.hook_runner.run_before(
        "render_chart", {"data": [1, 2, 3]}, state=None
    )
    assert isinstance(decision, Skip)
    assert decision.reason == "user has control"
    assert decision.stub_result == {
        "deferred": True,
        "tool_name": "render_chart",
        "message": "Tool deferred - user is driving the sandbox.",
    }


@pytest.mark.asyncio
async def test_takeover_gate_continues_when_inactive() -> None:
    """When takeover is off, the gate returns Continue (the run_before
    aggregation yields Continue if no other hook decides)."""
    from orqest.hooks import Continue

    gate = TakeoverGate(session_id="never-active-sid")
    decision = await gate.before_tool("any_tool", {}, state=None)
    assert isinstance(decision, Continue)


@pytest.mark.asyncio
async def test_takeover_gate_continues_when_runtime_missing() -> None:
    """A gate whose session id has no runtime row treats it as inactive."""
    from orqest.hooks import Continue

    gate = TakeoverGate(session_id="ghost-sid-never-built")
    decision = await gate.before_tool("any_tool", {}, state=None)
    assert isinstance(decision, Continue)


@pytest.mark.asyncio
async def test_chat_router_no_longer_409s_during_takeover(client) -> None:
    """Phase β.7: the router-side 409 block is gone. Tool deferral now
    happens at the hook layer (TakeoverGate -> Skip), not the router.

    This test confirms the router accepts the request and surfaces
    validation/auth errors instead of a 409 takeover-gate."""
    sid = await _make_session()
    await client.post(f"/sessions/{sid}/takeover")
    resp = await client.post(
        f"/sessions/{sid}/chat/stream",
        json={"messages": []},
    )
    # Whatever happens downstream, it is never the old 409 takeover block.
    assert resp.status_code != 409
