"""Tests for polymath.tools.report.

We don't run weasyprint or matplotlib here — the sandbox is faked. We
verify the tool wrappers shape the exec call, register the artifact,
emit lifecycle events, and route SandboxError into a JSON `error` field.
"""

from __future__ import annotations

import json
import types
from typing import Any
from uuid import uuid4

import pytest

from polymath import runtime as runtime_mod
from polymath.db.models import Session
from polymath.db.session import get_sessionmaker
from polymath.sandbox.manager import SandboxError
from polymath.state import PolymathState
from polymath.tools.report import _markdown_to_pdf, _render_chart


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._size = 1024
        self._exit = 0
        self._stderr = ""

    async def exec(self, sid: str, cmd: list[str], *, timeout_s: float = 120.0, **kw):
        self.calls.append(("exec", (sid, tuple(cmd), kw.get("env")), {"timeout_s": timeout_s}))
        if cmd[:2] == ["mkdir", "-p"]:
            return 0, "", "", False
        # Simulate the wrapper's final JSON line.
        out = json.dumps({"path": "x", "size": self._size}) + "\n"
        return self._exit, out, self._stderr, False


@pytest.fixture
def _fake_manager(monkeypatch: pytest.MonkeyPatch) -> _FakeManager:
    fake = _FakeManager()
    from polymath.tools import report as report_module
    monkeypatch.setattr(report_module, "get_manager", lambda: fake)
    return fake


async def _seed_session(sid: str) -> None:
    sm = get_sessionmaker()
    async with sm() as db:
        from uuid import UUID
        db.add(Session(id=UUID(sid), title="t"))
        await db.commit()


async def _run(tool_fn, state: PolymathState, **kwargs: Any) -> dict:
    ctx = types.SimpleNamespace(deps=state)
    return json.loads(await tool_fn(ctx, **kwargs))


@pytest.mark.asyncio
async def test_render_chart_creates_artifact(_fake_manager: _FakeManager) -> None:
    sid = str(uuid4())
    await _seed_session(sid)
    state = PolymathState(session_id=sid)
    result = await _run(
        _render_chart, state,
        code="plt.plot([1,2,3])", label="trend",
    )
    assert "artifact_id" in result
    assert result["path"].endswith(".png")
    assert result["size_bytes"] == 1024
    # mkdir + python wrapper exec
    assert len(_fake_manager.calls) == 2
    # User code is passed via env, not embedded in the shell string.
    env = _fake_manager.calls[1][1][2]
    assert env == {"POLYMATH_USER_CODE": "plt.plot([1,2,3])"}


@pytest.mark.asyncio
async def test_render_chart_error_branch(_fake_manager: _FakeManager) -> None:
    _fake_manager._exit = 1
    _fake_manager._stderr = "matplotlib boom"
    sid = str(uuid4())
    await _seed_session(sid)
    state = PolymathState(session_id=sid)
    result = await _run(_render_chart, state, code="bad")
    assert "error" in result
    assert "matplotlib boom" in result["error"]


@pytest.mark.asyncio
async def test_render_chart_emits_lifecycle_events(
    _fake_manager: _FakeManager,
) -> None:
    sid = str(uuid4())
    await _seed_session(sid)
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen: list[str] = []

    async def handler(evt) -> None:
        seen.append(evt.event_type)

    rt.workbench.event_bus.subscribe_all(handler)
    await _run(_render_chart, state, code="plt.plot([1])", label="x")
    assert "tool.report.render_chart.started" in seen
    assert "tool.report.render_chart.completed" in seen
    assert "artifact.created" in seen


@pytest.mark.asyncio
async def test_render_chart_emits_ui_chart_init(
    _fake_manager: _FakeManager,
) -> None:
    """Phase β: a successful ``_render_chart`` also fires ``ui.chart.init``.

    The typed event carries the ``ChartComponent`` envelope so the
    frontend can resolve a renderer through the generative-UI channel
    in addition to the legacy ``artifact.created`` event.
    """
    sid = str(uuid4())
    await _seed_session(sid)
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen: list[tuple[str, dict]] = []

    async def handler(evt) -> None:
        seen.append((evt.event_type, evt.data))

    rt.workbench.event_bus.subscribe_all(handler)
    result = await _run(_render_chart, state, code="plt.plot([1])", label="trend")

    types_emitted = [t for t, _ in seen]
    assert "artifact.created" in types_emitted
    assert "ui.chart.init" in types_emitted

    typed = next(d for t, d in seen if t == "ui.chart.init")
    assert typed["component_type"] == "chart"
    # component_id is keyed off the artifact id so the frontend can
    # round-trip back to the legacy artifact endpoint for the PNG.
    assert typed["component_id"] == f"chart-{result['artifact_id']}"
    assert typed["data"]["title"] == "trend"
    # PNG-backed: no inline series until the tool starts forwarding
    # structured plot data (see TODO in tools/report.py).
    assert typed["data"]["series"] == []
    assert typed["metadata"]["artifact_id"] == result["artifact_id"]
    assert typed["metadata"]["mime"] == "image/png"


@pytest.mark.asyncio
async def test_render_chart_no_ui_event_on_error(
    _fake_manager: _FakeManager,
) -> None:
    """A failed render must NOT emit ``ui.chart.init`` (no artifact yet)."""
    _fake_manager._exit = 1
    _fake_manager._stderr = "matplotlib boom"
    sid = str(uuid4())
    await _seed_session(sid)
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen: list[str] = []

    async def handler(evt) -> None:
        seen.append(evt.event_type)

    rt.workbench.event_bus.subscribe_all(handler)
    await _run(_render_chart, state, code="bad")
    assert "ui.chart.init" not in seen


@pytest.mark.asyncio
async def test_markdown_to_pdf_creates_artifact(_fake_manager: _FakeManager) -> None:
    sid = str(uuid4())
    await _seed_session(sid)
    state = PolymathState(session_id=sid)
    result = await _run(
        _markdown_to_pdf, state,
        markdown_text="# Hello\n\nbody.",
        label="my-report",
    )
    assert "artifact_id" in result
    assert result["path"].endswith(".pdf")
    env = _fake_manager.calls[1][1][2]
    assert env == {"POLYMATH_USER_MD": "# Hello\n\nbody."}


@pytest.mark.asyncio
async def test_markdown_to_pdf_error_branch(_fake_manager: _FakeManager) -> None:
    _fake_manager._exit = 1
    _fake_manager._stderr = "weasyprint exploded"
    sid = str(uuid4())
    await _seed_session(sid)
    state = PolymathState(session_id=sid)
    result = await _run(_markdown_to_pdf, state, markdown_text="# x")
    assert "error" in result
    assert "weasyprint" in result["error"]


@pytest.mark.asyncio
async def test_render_chart_sandbox_exception_routed_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised SandboxError still returns JSON `error` (no exception bubble)."""

    class _Boom:
        async def exec(self, *a, **kw):
            raise SandboxError("docker is down")

    from polymath.tools import report as report_module
    monkeypatch.setattr(report_module, "get_manager", lambda: _Boom())

    sid = str(uuid4())
    await _seed_session(sid)
    state = PolymathState(session_id=sid)
    result = await _run(_render_chart, state, code="plt.plot([])")
    assert result == {"error": "docker is down"}
