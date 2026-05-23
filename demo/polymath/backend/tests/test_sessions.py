"""Tests for /sessions CRUD including edge cases."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_session_default_title(client: AsyncClient) -> None:
    r = await client.post("/sessions", json={})
    assert r.status_code == 200
    body = r.json()
    assert uuid.UUID(body["id"])  # validates UUID shape
    assert body["title"] == "Untitled session"
    assert "created_at" in body


@pytest.mark.asyncio
async def test_create_session_with_title(client: AsyncClient) -> None:
    r = await client.post("/sessions", json={"title": "Hello"})
    assert r.status_code == 200
    assert r.json()["title"] == "Hello"


@pytest.mark.asyncio
async def test_create_session_no_body(client: AsyncClient) -> None:
    """Missing body still works — dict | None default gives Untitled session."""
    r = await client.post("/sessions")
    assert r.status_code == 200
    assert r.json()["title"] == "Untitled session"


@pytest.mark.asyncio
async def test_list_sessions_empty(client: AsyncClient) -> None:
    r = await client.get("/sessions")
    assert r.status_code == 200
    assert r.json()["sessions"] == []


@pytest.mark.asyncio
async def test_list_sessions_after_create(client: AsyncClient) -> None:
    await client.post("/sessions", json={"title": "a"})
    await client.post("/sessions", json={"title": "b"})
    r = await client.get("/sessions")
    assert r.status_code == 200
    titles = [s["title"] for s in r.json()["sessions"]]
    assert set(titles) == {"a", "b"}


@pytest.mark.asyncio
async def test_get_session_found(client: AsyncClient) -> None:
    sid = (await client.post("/sessions", json={"title": "found"})).json()["id"]
    r = await client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sid
    assert body["plan"] == {"tasks": []}
    assert body["artifacts"] == []


@pytest.mark.asyncio
async def test_get_session_not_found(client: AsyncClient) -> None:
    """Unknown UUID → 404, not 500 and not empty body."""
    r = await client.get(f"/sessions/{uuid.uuid4()}")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_session_bad_uuid(client: AsyncClient) -> None:
    """Non-UUID path param → 422 via pydantic validation, not 500."""
    r = await client.get("/sessions/not-a-uuid")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient) -> None:
    sid = (await client.post("/sessions")).json()["id"]
    r = await client.delete(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": sid}
    # Gone afterwards.
    r2 = await client.get(f"/sessions/{sid}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_delete_session_not_found(client: AsyncClient) -> None:
    r = await client.delete(f"/sessions/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_session_drops_runtime(client: AsyncClient) -> None:
    """DELETE must evict the per-session workbench so we don't leak memory."""
    from polymath import runtime

    sid = (await client.post("/sessions")).json()["id"]
    runtime.get_runtime(sid)  # force cache insert
    assert sid in runtime._runtimes

    r = await client.delete(f"/sessions/{sid}")
    assert r.status_code == 200
    assert sid not in runtime._runtimes
