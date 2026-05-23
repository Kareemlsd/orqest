"""Tests for ``polymath.tools.ui`` — emit / update / remove components.

We exercise the tools against the per-session
:class:`~polymath.workbench_factory.SessionRuntime`'s real
:class:`~orqest.observability.EventBus` so the emitted
``ui.<type>.{init,delta,remove}`` events flow on the same bus the SSE
sidecar consumes.
"""

from __future__ import annotations

import json
import types
from typing import Any
from uuid import uuid4

import pytest

from polymath import config as config_module
from polymath import runtime as runtime_mod
from polymath.state import PolymathState
from polymath.tools.ui import (
    _emit_component,
    _remove_component,
    _update_component,
)


async def _run(tool_fn, state: PolymathState, **kwargs: Any) -> dict:
    ctx = types.SimpleNamespace(deps=state)
    return json.loads(await tool_fn(ctx, **kwargs))


def _capture_events(rt) -> list[tuple[str, dict]]:
    seen: list[tuple[str, dict]] = []

    async def handler(evt) -> None:
        seen.append((evt.event_type, evt.data))

    rt.workbench.event_bus.subscribe_all(handler)
    return seen


# ---- emit_component ---------------------------------------------------


@pytest.mark.asyncio
async def test_emit_component_layout_round_trip() -> None:
    """A nested ``layout`` round-trips through validation + the bus."""
    sid = str(uuid4())
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen = _capture_events(rt)

    inner_text = {
        "component_type": "text",
        "component_id": "child-text",
        "data": {"content": "Hello"},
        "metadata": {},
    }
    result = await _run(
        _emit_component,
        state,
        component_type="layout",
        data={"direction": "horizontal", "gap": 12, "children": [inner_text]},
    )
    assert "component_id" in result
    assert result["component_type"] == "layout"

    types_emitted = [t for t, _ in seen]
    assert "ui.layout.init" in types_emitted

    init_payload = next(d for t, d in seen if t == "ui.layout.init")
    assert init_payload["component_type"] == "layout"
    assert init_payload["component_id"] == result["component_id"]
    assert init_payload["data"]["direction"] == "horizontal"
    assert init_payload["data"]["children"][0]["component_type"] == "text"


@pytest.mark.asyncio
async def test_emit_component_unknown_type_returns_error() -> None:
    sid = str(uuid4())
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen = _capture_events(rt)

    result = await _run(
        _emit_component,
        state,
        component_type="not_a_real_type",
        data={},
    )
    assert "error" in result
    assert "unknown component_type" in result["error"]
    # No event flowed for the unknown type.
    assert not any(t.startswith("ui.not_a_real_type") for t, _ in seen)


@pytest.mark.asyncio
async def test_emit_component_validation_error_returned() -> None:
    """A malformed `chart` data payload surfaces as JSON error."""
    sid = str(uuid4())
    state = PolymathState(session_id=sid)

    result = await _run(
        _emit_component,
        state,
        component_type="chart",
        # ``chart_kind`` Literal rejects "3d-rotational".
        data={"chart_kind": "3d-rotational", "title": "bad"},
    )
    assert "error" in result
    assert "validation failed" in result["error"]


@pytest.mark.asyncio
async def test_emit_component_sandboxed_html_gated_when_disabled(
    monkeypatch: pytest.MonkeyPatch, _frozen_config
) -> None:
    """``sandboxed_html`` is rejected when ENABLE_SANDBOXED_HTML is off."""
    # The flag defaults on for the demo (so the Canvas can showcase Layer 3
    # out of the box); this test forces it off via env to exercise the gate.
    monkeypatch.setenv("POLYMATH_ENABLE_SANDBOXED_HTML", "0")
    config_module.get_default_config.cache_clear()

    sid = str(uuid4())
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen = _capture_events(rt)

    result = await _run(
        _emit_component,
        state,
        component_type="sandboxed_html",
        data={"html": "<p>blocked</p>"},
    )
    assert "error" in result
    assert "POLYMATH_ENABLE_SANDBOXED_HTML" in result["error"]
    assert not any(t.startswith("ui.sandboxed_html") for t, _ in seen)


@pytest.mark.asyncio
async def test_emit_component_sandboxed_html_allowed_when_enabled(
    monkeypatch: pytest.MonkeyPatch, _frozen_config
) -> None:
    """When the flag is on, sandboxed_html emits ``ui.sandboxed_html.init``."""
    monkeypatch.setenv("POLYMATH_ENABLE_SANDBOXED_HTML", "1")
    config_module.get_default_config.cache_clear()

    sid = str(uuid4())
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen = _capture_events(rt)

    result = await _run(
        _emit_component,
        state,
        component_type="sandboxed_html",
        data={"html": "<svg></svg>", "height_px": 100},
    )
    assert "component_id" in result
    types_emitted = [t for t, _ in seen]
    assert "ui.sandboxed_html.init" in types_emitted


@pytest.mark.asyncio
async def test_emit_component_assigns_component_id_when_omitted() -> None:
    sid = str(uuid4())
    state = PolymathState(session_id=sid)

    result = await _run(
        _emit_component,
        state,
        component_type="text",
        data={"content": "auto-id"},
    )
    assert result["component_id"].startswith("text-")


@pytest.mark.asyncio
async def test_emit_component_preserves_provided_component_id() -> None:
    sid = str(uuid4())
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen = _capture_events(rt)

    await _run(
        _emit_component,
        state,
        component_type="text",
        component_id="my-stable-id",
        data={"content": "hi"},
    )
    init_payload = next(d for t, d in seen if t == "ui.text.init")
    assert init_payload["component_id"] == "my-stable-id"


# ---- update_component -------------------------------------------------


@pytest.mark.asyncio
async def test_update_component_emits_delta_event() -> None:
    sid = str(uuid4())
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen = _capture_events(rt)

    emitted = await _run(
        _emit_component,
        state,
        component_type="layout",
        data={"direction": "vertical", "children": []},
    )
    cid = emitted["component_id"]

    update_result = await _run(
        _update_component,
        state,
        component_id=cid,
        component_type="layout",
        op="append",
        path="children",
        value={
            "component_type": "text",
            "component_id": "child-1",
            "data": {"content": "appended"},
            "metadata": {},
        },
    )
    assert update_result["ok"] is True

    deltas = [(t, d) for t, d in seen if t == "ui.layout.delta"]
    assert len(deltas) == 1
    delta_payload = deltas[0][1]
    assert delta_payload["op"] == "append"
    assert delta_payload["path"] == "children"
    assert delta_payload["component_id"] == cid
    assert delta_payload["value"]["data"]["content"] == "appended"


@pytest.mark.asyncio
async def test_update_component_invalid_op_returns_error() -> None:
    sid = str(uuid4())
    state = PolymathState(session_id=sid)

    result = await _run(
        _update_component,
        state,
        component_id="x",
        component_type="text",
        op="overwrite",  # not a valid UIDeltaOp
    )
    assert "error" in result
    assert "invalid op" in result["error"]


@pytest.mark.asyncio
async def test_update_component_unknown_type_returns_error() -> None:
    sid = str(uuid4())
    state = PolymathState(session_id=sid)

    result = await _run(
        _update_component,
        state,
        component_id="x",
        component_type="not_a_real_type",
        op="replace",
    )
    assert "error" in result
    assert "unknown component_type" in result["error"]


# ---- remove_component -------------------------------------------------


@pytest.mark.asyncio
async def test_remove_component_emits_remove_event() -> None:
    sid = str(uuid4())
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen = _capture_events(rt)

    emitted = await _run(
        _emit_component,
        state,
        component_type="badge",
        data={"label": "ok", "tone": "success"},
    )
    cid = emitted["component_id"]

    result = await _run(
        _remove_component,
        state,
        component_id=cid,
        component_type="badge",
    )
    assert result["ok"] is True

    types_emitted = [t for t, _ in seen]
    assert "ui.badge.remove" in types_emitted
    remove_payload = next(d for t, d in seen if t == "ui.badge.remove")
    assert remove_payload["component_id"] == cid


@pytest.mark.asyncio
async def test_remove_component_unknown_type_returns_error() -> None:
    sid = str(uuid4())
    state = PolymathState(session_id=sid)

    result = await _run(
        _remove_component,
        state,
        component_id="x",
        component_type="not_a_real_type",
    )
    assert "error" in result
    assert "unknown component_type" in result["error"]
