"""Tests for the per-session metrics aggregator + cumulative_usage exposure."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_record_turn_accumulates_per_session() -> None:
    from polymath.session_metrics import cumulative_for, record_turn, reset

    reset()
    sid = "test-session-acc"
    record_turn(
        sid,
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        tool_calls=2,
        duration_ms=1234.0,
    )
    record_turn(
        sid,
        input_tokens=200,
        output_tokens=80,
        total_tokens=280,
        tool_calls=1,
        duration_ms=900.0,
    )
    snap = cumulative_for(sid)
    assert snap["input_tokens"] == 300
    assert snap["output_tokens"] == 130
    assert snap["total_tokens"] == 430
    assert snap["tool_calls"] == 3
    assert snap["turns"] == 2
    assert snap["total_duration_ms"] == pytest.approx(2134.0)


@pytest.mark.asyncio
async def test_cumulative_for_unseen_session_returns_zeros() -> None:
    from polymath.session_metrics import cumulative_for, reset

    reset()
    snap = cumulative_for("never-recorded")
    assert snap["input_tokens"] == 0
    assert snap["output_tokens"] == 0
    assert snap["total_tokens"] == 0
    assert snap["tool_calls"] == 0
    assert snap["turns"] == 0


@pytest.mark.asyncio
async def test_record_turn_isolates_sessions() -> None:
    from polymath.session_metrics import cumulative_for, record_turn, reset

    reset()
    record_turn(
        "session-a",
        input_tokens=10, output_tokens=5, total_tokens=15,
        tool_calls=1, duration_ms=100.0,
    )
    record_turn(
        "session-b",
        input_tokens=999, output_tokens=999, total_tokens=1998,
        tool_calls=99, duration_ms=99000.0,
    )
    a = cumulative_for("session-a")
    b = cumulative_for("session-b")
    assert a["input_tokens"] == 10
    assert b["input_tokens"] == 999
    assert a["tool_calls"] == 1
    assert b["tool_calls"] == 99


@pytest.mark.asyncio
async def test_reset_clears_one_session_only() -> None:
    from polymath.session_metrics import cumulative_for, record_turn, reset

    reset()
    record_turn("keep", input_tokens=1, output_tokens=1, total_tokens=2,
                tool_calls=0, duration_ms=10.0)
    record_turn("drop", input_tokens=5, output_tokens=5, total_tokens=10,
                tool_calls=0, duration_ms=50.0)
    reset("drop")
    assert cumulative_for("keep")["input_tokens"] == 1
    assert cumulative_for("drop")["input_tokens"] == 0  # zeros for unseen


@pytest.mark.asyncio
async def test_get_session_includes_cumulative_usage(client: AsyncClient) -> None:
    """GET /sessions/{sid} must surface the cumulative_usage block."""
    from polymath.session_metrics import record_turn, reset

    reset()
    sid = (await client.post("/sessions")).json()["id"]
    # Pre-seed some metrics so the endpoint doesn't just return zeros.
    record_turn(
        sid,
        input_tokens=42, output_tokens=21, total_tokens=63,
        tool_calls=4, duration_ms=1234.5,
    )
    r = await client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert "cumulative_usage" in body
    cu = body["cumulative_usage"]
    assert cu["input_tokens"] == 42
    assert cu["output_tokens"] == 21
    assert cu["total_tokens"] == 63
    assert cu["tool_calls"] == 4
    assert cu["turns"] == 1


@pytest.mark.asyncio
async def test_event_types_manifest_includes_chat_turn_completed(
    client: AsyncClient,
) -> None:
    """Frontend SidecarProvider learns the new event type from this list."""
    sid = (await client.post("/sessions")).json()["id"]
    r = await client.get(f"/sessions/{sid}/ui/event-types")
    assert r.status_code == 200
    types = r.json()["event_types"]
    assert "chat.turn.completed" in types
