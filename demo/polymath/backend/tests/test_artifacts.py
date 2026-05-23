"""Tests for the artifact registry — DB persistence + event emission +
HTTP routes (list + download).

We don't spin up a real sandbox here. The download route is exercised
with a fake ``SandboxManager`` that serves canned bytes for a path.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from polymath import runtime as runtime_mod
from polymath.artifacts.store import create_artifact, get_artifact, list_artifacts
from polymath.db.models import Session
from polymath.db.session import get_sessionmaker


async def _make_session() -> UUID:
    sm = get_sessionmaker()
    sid = uuid4()
    async with sm() as db:
        db.add(Session(id=sid, title="t"))
        await db.commit()
    return sid


@pytest.mark.asyncio
async def test_create_artifact_persists_row() -> None:
    sid = await _make_session()
    art = await create_artifact(
        session_id=sid,
        kind="chart",
        mime="image/png",
        label="parabola",
        path=".polymath/artifacts/chart-x.png",
        size_bytes=128,
    )
    assert art.kind == "chart"
    assert art.size_bytes == 128
    rows = await list_artifacts(sid)
    assert [r.id for r in rows] == [art.id]


@pytest.mark.asyncio
async def test_list_artifacts_orders_newest_first() -> None:
    sid = await _make_session()
    a = await create_artifact(
        session_id=sid, kind="chart", mime="image/png",
        label="a", path="a.png", size_bytes=1,
    )
    b = await create_artifact(
        session_id=sid, kind="report", mime="application/pdf",
        label="b", path="b.pdf", size_bytes=2,
    )
    rows = await list_artifacts(sid)
    assert [r.id for r in rows][:2] == [b.id, a.id]


@pytest.mark.asyncio
async def test_get_artifact_returns_none_for_unknown() -> None:
    assert await get_artifact(uuid4()) is None


@pytest.mark.asyncio
async def test_create_artifact_emits_event() -> None:
    sid = await _make_session()
    rt = runtime_mod.get_runtime(str(sid))
    seen: list[Any] = []

    async def handler(evt) -> None:
        if evt.event_type == "artifact.created":
            seen.append(evt.data)

    rt.workbench.event_bus.subscribe_all(handler)
    art = await create_artifact(
        session_id=sid, kind="chart", mime="image/png",
        label="x", path="x.png", size_bytes=42,
    )
    assert seen and seen[0]["id"] == str(art.id)
    assert seen[0]["kind"] == "chart"
    assert seen[0]["size"] == 42


# ---- HTTP routes -----------------------------------------------------


class _FakeManager:
    """Minimal ``SandboxManager`` substitute for the download route."""

    def __init__(self, fs: dict[str, bytes] | None = None) -> None:
        self._fs = fs or {}

    async def get_file(self, sid: str, path: str, *, max_bytes: int = 200_000):
        if path not in self._fs:
            from polymath.sandbox.manager import SandboxError
            raise SandboxError(f"{path} not found")
        data = self._fs[path]
        return data[:max_bytes], len(data) > max_bytes


@pytest.fixture
def _fake_sandbox(monkeypatch: pytest.MonkeyPatch) -> _FakeManager:
    fake = _FakeManager()
    from polymath.routers import artifacts as artifacts_router
    monkeypatch.setattr(artifacts_router, "get_manager", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_route_list_artifacts(client, _fake_sandbox) -> None:
    sid = await _make_session()
    await create_artifact(
        session_id=sid, kind="chart", mime="image/png",
        label="lbl", path="p.png", size_bytes=7,
    )
    resp = await client.get(f"/sessions/{sid}/artifacts")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["artifacts"]) == 1
    a = body["artifacts"][0]
    assert a["kind"] == "chart" and a["size_bytes"] == 7 and a["label"] == "lbl"


@pytest.mark.asyncio
async def test_route_download_artifact(client, _fake_sandbox) -> None:
    sid = await _make_session()
    art = await create_artifact(
        session_id=sid, kind="report", mime="application/pdf",
        label="rep", path="r.pdf", size_bytes=4,
    )
    _fake_sandbox._fs["r.pdf"] = b"%PDF"
    resp = await client.get(f"/sessions/{sid}/artifacts/{art.id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.headers["x-polymath-truncated"] == "0"
    assert resp.content == b"%PDF"


@pytest.mark.asyncio
async def test_route_download_404_unknown_artifact(client, _fake_sandbox) -> None:
    sid = await _make_session()
    resp = await client.get(f"/sessions/{sid}/artifacts/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_route_download_rejects_cross_session(client, _fake_sandbox) -> None:
    """Cannot download an artifact belonging to a different session."""
    sid_a = await _make_session()
    sid_b = await _make_session()
    art = await create_artifact(
        session_id=sid_a, kind="chart", mime="image/png",
        label="x", path="x.png", size_bytes=1,
    )
    _fake_sandbox._fs["x.png"] = b"\x89PNG"
    resp = await client.get(f"/sessions/{sid_b}/artifacts/{art.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_route_download_404_when_file_missing(client, _fake_sandbox) -> None:
    """DB row exists but the sandbox volume is gone — reports 404, not 500."""
    sid = await _make_session()
    art = await create_artifact(
        session_id=sid, kind="chart", mime="image/png",
        label="x", path="missing.png", size_bytes=10,
    )
    resp = await client.get(f"/sessions/{sid}/artifacts/{art.id}")
    assert resp.status_code == 404
