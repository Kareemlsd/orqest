"""Tests for the agent-facing right-pane tab tools.

Covers ``open_tab`` / ``update_tab`` / ``close_tab`` invocations through
the same execution surface the agent uses (the underlying coroutine, not
HTTP) and verifies that the matching ``tab.*`` events fire on the
session's bus.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from polymath.state import PolymathState
from polymath.tools.tabs import _close_tab, _open_tab, _update_tab


class _FakeRunContext:
    """Minimal stand-in for pydantic-ai's RunContext — only ``deps`` is used."""

    def __init__(self, state: PolymathState) -> None:
        self.deps = state


def _capture_events(rt) -> list[tuple[str, dict]]:
    seen: list[tuple[str, dict]] = []

    def _listener(event):
        seen.append((event.event_type, event.data))

    rt.workbench.event_bus.subscribe_all(_listener)
    return seen


# ---- open_tab ---------------------------------------------------------


@pytest.mark.asyncio
async def test_open_tab_creates_row_and_emits_event(client: AsyncClient) -> None:
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)
    state = PolymathState(session_id=sid)
    seen = _capture_events(rt)
    seen.clear()

    raw = await _open_tab(
        _FakeRunContext(state),
        kind="component",
        title="Q3 Results",
    )
    payload = json.loads(raw)
    assert "tab_id" in payload
    assert payload["kind"] == "component"
    assert payload["title"] == "Q3 Results"
    assert UUID(payload["tab_id"])  # validates UUID shape

    # Row visible via REST.
    listed = await client.get(f"/sessions/{sid}/tabs")
    ids = [t["id"] for t in listed.json()["tabs"]]
    assert payload["tab_id"] in ids

    # Bus event emitted.
    assert any(et == "tab.opened" for et, _ in seen)


@pytest.mark.asyncio
async def test_open_tab_invalid_kind_returns_error_json(
    client: AsyncClient,
) -> None:
    sid = (await client.post("/sessions")).json()["id"]
    state = PolymathState(session_id=sid)
    raw = await _open_tab(
        _FakeRunContext(state),
        kind="not-a-real-kind",
        title="X",
    )
    payload = json.loads(raw)
    assert "error" in payload


# ---- update_tab -------------------------------------------------------


@pytest.mark.asyncio
async def test_update_tab_renames_and_focuses(client: AsyncClient) -> None:
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)
    state = PolymathState(session_id=sid)

    open_raw = await _open_tab(_FakeRunContext(state), kind="component", title="A")
    tab_id = json.loads(open_raw)["tab_id"]

    seen = _capture_events(rt)
    seen.clear()

    raw = await _update_tab(
        _FakeRunContext(state),
        tab_id=tab_id,
        title="A renamed",
        focus=True,
    )
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["focus"] is True

    listed = await client.get(f"/sessions/{sid}/tabs")
    body = listed.json()
    assert body["active_tab_id"] == tab_id
    by_id = {t["id"]: t for t in body["tabs"]}
    assert by_id[tab_id]["title"] == "A renamed"

    # Both updated + focused events fired.
    types = [et for et, _ in seen]
    assert "tab.updated" in types
    assert "tab.focused" in types


@pytest.mark.asyncio
async def test_update_tab_focus_only_does_not_emit_updated(
    client: AsyncClient,
) -> None:
    """Focus-only changes emit `tab.focused` but skip `tab.updated`."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)
    state = PolymathState(session_id=sid)

    open_raw = await _open_tab(_FakeRunContext(state), kind="component", title="A")
    tab_id = json.loads(open_raw)["tab_id"]

    seen = _capture_events(rt)
    seen.clear()

    await _update_tab(_FakeRunContext(state), tab_id=tab_id, focus=True)
    types = [et for et, _ in seen]
    assert "tab.focused" in types
    assert "tab.updated" not in types


@pytest.mark.asyncio
async def test_update_tab_unknown_id_returns_error(client: AsyncClient) -> None:
    sid = (await client.post("/sessions")).json()["id"]
    state = PolymathState(session_id=sid)
    raw = await _update_tab(
        _FakeRunContext(state), tab_id=str(uuid4()), title="x"
    )
    assert "error" in json.loads(raw)


# ---- close_tab --------------------------------------------------------


@pytest.mark.asyncio
async def test_close_tab_soft_deletes(client: AsyncClient) -> None:
    sid = (await client.post("/sessions")).json()["id"]
    state = PolymathState(session_id=sid)

    open_raw = await _open_tab(_FakeRunContext(state), kind="component", title="X")
    tab_id = json.loads(open_raw)["tab_id"]

    raw = await _close_tab(_FakeRunContext(state), tab_id=tab_id)
    assert json.loads(raw)["ok"] is True

    listed = await client.get(f"/sessions/{sid}/tabs")
    by_id = {t["id"]: t for t in listed.json()["tabs"]}
    assert by_id[tab_id]["status"] == "closed"
    assert by_id[tab_id]["closed_at"] is not None


# ---- emit_component honoring target_tab_id ----------------------------


@pytest.mark.asyncio
async def test_emit_component_without_target_tab_id_spawns_tab(
    client: AsyncClient,
) -> None:
    """Default behaviour: each emit opens its own component tab."""
    from polymath.tools.ui import _emit_component

    sid = (await client.post("/sessions")).json()["id"]
    state = PolymathState(session_id=sid)
    raw = await _emit_component(
        _FakeRunContext(state),
        component_type="markdown",
        data={"content": "# Hello"},
    )
    payload = json.loads(raw)
    assert payload.get("tab_id")
    assert UUID(payload["tab_id"])

    # The fresh tab is visible in the manifest with the component bound.
    listed = await client.get(f"/sessions/{sid}/tabs")
    by_id = {t["id"]: t for t in listed.json()["tabs"]}
    spawned = by_id[payload["tab_id"]]
    assert spawned["kind"] == "component"
    assert spawned["content_ref"]["component_ids"] == [payload["component_id"]]


@pytest.mark.asyncio
async def test_emit_component_with_target_tab_id_appends(
    client: AsyncClient,
) -> None:
    """Passing metadata.target_tab_id binds the component to an existing tab."""
    from polymath.tools.ui import _emit_component

    sid = (await client.post("/sessions")).json()["id"]
    state = PolymathState(session_id=sid)

    open_raw = await _open_tab(
        _FakeRunContext(state), kind="component", title="Group"
    )
    tid = json.loads(open_raw)["tab_id"]

    a_raw = await _emit_component(
        _FakeRunContext(state),
        component_type="markdown",
        data={"content": "first"},
        metadata={"target_tab_id": tid},
    )
    b_raw = await _emit_component(
        _FakeRunContext(state),
        component_type="markdown",
        data={"content": "second"},
        metadata={"target_tab_id": tid},
    )
    a_payload = json.loads(a_raw)
    b_payload = json.loads(b_raw)
    assert a_payload["tab_id"] == tid
    assert b_payload["tab_id"] == tid

    listed = await client.get(f"/sessions/{sid}/tabs")
    by_id = {t["id"]: t for t in listed.json()["tabs"]}
    bound = by_id[tid]["content_ref"]["component_ids"]
    assert a_payload["component_id"] in bound
    assert b_payload["component_id"] in bound
    # No extra component-kind tabs got spawned.
    component_kinds = [
        t for t in listed.json()["tabs"] if t["kind"] == "component" and t["status"] == "open"
    ]
    assert len(component_kinds) == 1


@pytest.mark.asyncio
async def test_emit_component_invalid_target_tab_id_falls_back_to_spawn(
    client: AsyncClient,
) -> None:
    """A bogus target_tab_id silently falls back to spawning a fresh tab."""
    from polymath.tools.ui import _emit_component

    sid = (await client.post("/sessions")).json()["id"]
    state = PolymathState(session_id=sid)

    raw = await _emit_component(
        _FakeRunContext(state),
        component_type="markdown",
        data={"content": "stranded"},
        metadata={"target_tab_id": str(uuid4())},
    )
    payload = json.loads(raw)
    assert payload.get("tab_id")
    listed = await client.get(f"/sessions/{sid}/tabs")
    component_kinds = [
        t
        for t in listed.json()["tabs"]
        if t["kind"] == "component" and t["status"] == "open"
    ]
    # One spawned (the fallback). 0 + 1 = 1.
    assert len(component_kinds) == 1
