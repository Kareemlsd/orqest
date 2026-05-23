"""Tests for the right-pane tab manifest router.

Covers GET (open + tombstoned), POST (idempotency on client-supplied id +
auto-position), PATCH (title / position / pinned / status / content_ref),
DELETE (soft-close + active_tab clearing), restore, reorder, and focus.

Each test uses the `client` + `_isolated_db` fixtures in
``tests/conftest.py`` so the SQLite tables are fresh per test.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


# ---- helpers -----------------------------------------------------------


async def _new_session(client: AsyncClient) -> str:
    """Create a session and return its id."""
    r = await client.post("/sessions", json={})
    assert r.status_code == 200
    return r.json()["id"]


async def _open_tab(
    client: AsyncClient,
    sid: str,
    *,
    kind: str = "component",
    title: str = "T",
    **extra,
) -> dict:
    payload = {"kind": kind, "title": title, **extra}
    r = await client.post(f"/sessions/{sid}/tabs", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ---- list --------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_seeds_shell_and_files_tabs(client: AsyncClient) -> None:
    """Phase A spec: new sessions land with Shell + Files open."""
    sid = await _new_session(client)
    r = await client.get(f"/sessions/{sid}/tabs")
    assert r.status_code == 200
    body = r.json()
    kinds = sorted(t["kind"] for t in body["tabs"])
    assert kinds == ["files", "shell"]
    # Each seeded tab has a stable position so the strip ordering is deterministic.
    positions = {t["kind"]: t["position"] for t in body["tabs"]}
    assert positions["shell"] != positions["files"]
    # No active tab is set on session creation — frontend chooses the default.
    assert body["active_tab_id"] is None


@pytest.mark.asyncio
async def test_list_includes_closed_within_24h_by_default(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="A")
    r = await client.delete(f"/sessions/{sid}/tabs/{tab['id']}")
    assert r.status_code == 200
    # Default include_closed=true returns tombstones.
    r = await client.get(f"/sessions/{sid}/tabs")
    closed_ids = [t["id"] for t in r.json()["tabs"] if t["status"] == "closed"]
    assert tab["id"] in closed_ids
    # include_closed=false hides them.
    r = await client.get(f"/sessions/{sid}/tabs", params={"include_closed": "false"})
    closed_ids = [t["id"] for t in r.json()["tabs"] if t["status"] == "closed"]
    assert closed_ids == []


# ---- create ------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tab_assigns_position_at_end(client: AsyncClient) -> None:
    sid = await _new_session(client)
    # Two seeded tabs already exist (positions 0 and 1).
    new = await _open_tab(client, sid, kind="component", title="C")
    assert new["position"] == 2


@pytest.mark.asyncio
async def test_create_tab_idempotent_on_client_id(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tid = str(uuid.uuid4())
    a = await _open_tab(client, sid, id=tid, kind="component", title="X")
    b = await _open_tab(client, sid, id=tid, kind="component", title="Y")
    assert a["id"] == b["id"] == tid
    # Second call returns the existing row — title NOT updated, that's
    # PATCH's job.
    assert b["title"] == "X"


@pytest.mark.asyncio
async def test_create_tab_invalid_kind_returns_422(client: AsyncClient) -> None:
    sid = await _new_session(client)
    r = await client.post(
        f"/sessions/{sid}/tabs", json={"kind": "not-a-real-kind", "title": "X"}
    )
    assert r.status_code == 422


# ---- patch -------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_tab_updates_title(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="orig")
    r = await client.patch(
        f"/sessions/{sid}/tabs/{tab['id']}", json={"title": "renamed"}
    )
    assert r.status_code == 200
    assert r.json()["title"] == "renamed"


@pytest.mark.asyncio
async def test_patch_tab_status_closed_stamps_closed_at(
    client: AsyncClient,
) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="X")
    r = await client.patch(
        f"/sessions/{sid}/tabs/{tab['id']}", json={"status": "closed"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None


@pytest.mark.asyncio
async def test_patch_tab_404_for_unknown_id(client: AsyncClient) -> None:
    sid = await _new_session(client)
    r = await client.patch(
        f"/sessions/{sid}/tabs/{uuid.uuid4()}", json={"title": "x"}
    )
    assert r.status_code == 404


# ---- delete (soft-close) ----------------------------------------------


@pytest.mark.asyncio
async def test_delete_tab_is_soft_close(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="X")
    r = await client.delete(f"/sessions/{sid}/tabs/{tab['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None
    # Row still exists — DELETE is idempotent.
    again = await client.delete(f"/sessions/{sid}/tabs/{tab['id']}")
    assert again.status_code == 200
    assert again.json()["status"] == "closed"


@pytest.mark.asyncio
async def test_delete_active_tab_clears_session_pointer(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="X")
    # Focus it.
    fr = await client.post(f"/sessions/{sid}/tabs/{tab['id']}/focus")
    assert fr.status_code == 200
    # Sanity — list shows it as active.
    listed = await client.get(f"/sessions/{sid}/tabs")
    assert listed.json()["active_tab_id"] == tab["id"]
    # Close — pointer should clear.
    await client.delete(f"/sessions/{sid}/tabs/{tab['id']}")
    listed = await client.get(f"/sessions/{sid}/tabs")
    assert listed.json()["active_tab_id"] is None


# ---- restore -----------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_revives_a_closed_tab(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="X")
    await client.delete(f"/sessions/{sid}/tabs/{tab['id']}")
    r = await client.post(f"/sessions/{sid}/tabs/{tab['id']}/restore")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "open"
    assert body["closed_at"] is None


@pytest.mark.asyncio
async def test_restore_409_if_never_closed(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="X")
    r = await client.post(f"/sessions/{sid}/tabs/{tab['id']}/restore")
    assert r.status_code == 409


# ---- reorder -----------------------------------------------------------


@pytest.mark.asyncio
async def test_reorder_applies_new_positions(client: AsyncClient) -> None:
    sid = await _new_session(client)
    a = await _open_tab(client, sid, kind="component", title="A")
    b = await _open_tab(client, sid, kind="component", title="B")
    c = await _open_tab(client, sid, kind="component", title="C")
    # Reverse: c, b, a → positions 0, 1, 2.
    r = await client.post(
        f"/sessions/{sid}/tabs/reorder",
        json={"order": [c["id"], b["id"], a["id"]]},
    )
    assert r.status_code == 200
    listed = await client.get(f"/sessions/{sid}/tabs")
    by_id = {t["id"]: t for t in listed.json()["tabs"]}
    assert by_id[c["id"]]["position"] == 0
    assert by_id[b["id"]]["position"] == 1
    assert by_id[a["id"]]["position"] == 2


@pytest.mark.asyncio
async def test_reorder_partial_subset_leaves_others_alone(
    client: AsyncClient,
) -> None:
    sid = await _new_session(client)
    a = await _open_tab(client, sid, kind="component", title="A", position=10)
    b = await _open_tab(client, sid, kind="component", title="B", position=20)
    c = await _open_tab(client, sid, kind="component", title="C", position=30)
    # Reorder only [b, a] — c keeps position=30.
    await client.post(
        f"/sessions/{sid}/tabs/reorder",
        json={"order": [b["id"], a["id"]]},
    )
    listed = await client.get(f"/sessions/{sid}/tabs")
    by_id = {t["id"]: t for t in listed.json()["tabs"]}
    assert by_id[b["id"]]["position"] == 0
    assert by_id[a["id"]]["position"] == 1
    assert by_id[c["id"]]["position"] == 30


# ---- focus -------------------------------------------------------------


@pytest.mark.asyncio
async def test_focus_sets_session_active_tab(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="X")
    r = await client.post(f"/sessions/{sid}/tabs/{tab['id']}/focus")
    assert r.status_code == 200
    listed = await client.get(f"/sessions/{sid}/tabs")
    assert listed.json()["active_tab_id"] == tab["id"]


@pytest.mark.asyncio
async def test_focus_409_for_closed_tab(client: AsyncClient) -> None:
    sid = await _new_session(client)
    tab = await _open_tab(client, sid, kind="component", title="X")
    await client.delete(f"/sessions/{sid}/tabs/{tab['id']}")
    r = await client.post(f"/sessions/{sid}/tabs/{tab['id']}/focus")
    assert r.status_code == 409


# ---- bus emission ------------------------------------------------------


@pytest.mark.asyncio
async def test_open_tab_emits_tab_opened_event(client: AsyncClient) -> None:
    """Mutations publish a typed event on the session's bus."""
    from polymath.runtime import get_runtime

    sid = await _new_session(client)
    rt = get_runtime(sid)
    seen: list[tuple[str, dict]] = []

    def _capture(event):
        seen.append((event.event_type, event.data))

    rt.workbench.event_bus.subscribe_all(_capture)
    seen.clear()  # ignore replay of seed events

    await _open_tab(client, sid, kind="component", title="bus-test")
    types = [t for t, _ in seen]
    assert "tab.opened" in types


@pytest.mark.asyncio
async def test_event_types_manifest_includes_tab_events(client: AsyncClient) -> None:
    """The frontend's SidecarProvider learns the new event types from this."""
    sid = await _new_session(client)
    r = await client.get(f"/sessions/{sid}/ui/event-types")
    assert r.status_code == 200
    types = r.json()["event_types"]
    for et in (
        "tab.opened",
        "tab.updated",
        "tab.closed",
        "tab.focused",
        "tab.restored",
    ):
        assert et in types
