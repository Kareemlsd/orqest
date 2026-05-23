"""Tests for the auto-respawn middleware.

Verifies that closing a system tab and re-firing the corresponding event
family resurrects it — the key invariant behind the **lazy spawn,
closeable** UX choice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient

from orqest.observability import AgentEvent


async def _emit(rt, event_type: str, data: dict | None = None) -> None:
    """Push a fake AgentEvent through the session's bus."""
    await rt.workbench.event_bus.emit(
        AgentEvent(
            event_type=event_type,
            agent_name="test",
            timestamp=datetime.now(UTC),
            data=data or {},
        )
    )


async def _open_kinds(client: AsyncClient, sid: str) -> list[str]:
    r = await client.get(f"/sessions/{sid}/tabs")
    return [t["kind"] for t in r.json()["tabs"] if t["status"] == "open"]


# ---- spawn-on-event ---------------------------------------------------


@pytest.mark.asyncio
async def test_shell_event_spawns_shell_tab(client: AsyncClient) -> None:
    """A shell event respawns the Shell tab when it has been closed."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    # Close the seeded shell tab.
    listed = await client.get(f"/sessions/{sid}/tabs")
    shell = next(t for t in listed.json()["tabs"] if t["kind"] == "shell")
    await client.delete(f"/sessions/{sid}/tabs/{shell['id']}")
    assert "shell" not in await _open_kinds(client, sid)

    # Fire a shell event — the handler should reopen Shell.
    await _emit(rt, "shell.stdout", {"line": "hello"})
    assert "shell" in await _open_kinds(client, sid)


@pytest.mark.asyncio
async def test_tool_shell_event_also_respawns(client: AsyncClient) -> None:
    """``tool.shell.run_command.started`` also triggers respawn."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    listed = await client.get(f"/sessions/{sid}/tabs")
    shell = next(t for t in listed.json()["tabs"] if t["kind"] == "shell")
    await client.delete(f"/sessions/{sid}/tabs/{shell['id']}")

    await _emit(rt, "tool.shell.run_command.started", {"args": {"command": "ls"}})
    assert "shell" in await _open_kinds(client, sid)


@pytest.mark.asyncio
async def test_list_dir_event_spawns_files_tab(client: AsyncClient) -> None:
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    listed = await client.get(f"/sessions/{sid}/tabs")
    files = next(t for t in listed.json()["tabs"] if t["kind"] == "files")
    await client.delete(f"/sessions/{sid}/tabs/{files['id']}")
    assert "files" not in await _open_kinds(client, sid)

    await _emit(rt, "tool.fs.list_dir.completed", {"args": {"path": "/workspace"}})
    assert "files" in await _open_kinds(client, sid)


@pytest.mark.asyncio
async def test_write_file_event_spawns_editor_tab_per_path(
    client: AsyncClient,
) -> None:
    """Distinct paths get distinct editor tabs (browser-style)."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    await _emit(
        rt,
        "tool.fs.write_file.completed",
        {"args": {"path": "/workspace/a.py"}},
    )
    await _emit(
        rt,
        "tool.fs.write_file.completed",
        {"args": {"path": "/workspace/b.py"}},
    )

    r = await client.get(f"/sessions/{sid}/tabs")
    editor_paths = sorted(
        (t["content_ref"] or {}).get("path", "")
        for t in r.json()["tabs"]
        if t["kind"] == "editor" and t["status"] == "open"
    )
    assert editor_paths == ["/workspace/a.py", "/workspace/b.py"]


@pytest.mark.asyncio
async def test_write_file_same_path_idempotent(client: AsyncClient) -> None:
    """Same path → same editor tab; only one row is created."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    for _ in range(3):
        await _emit(
            rt,
            "tool.fs.edit_file.completed",
            {"args": {"path": "/workspace/main.py"}},
        )

    r = await client.get(f"/sessions/{sid}/tabs")
    editor_tabs = [
        t for t in r.json()["tabs"] if t["kind"] == "editor" and t["status"] == "open"
    ]
    assert len(editor_tabs) == 1
    assert editor_tabs[0]["content_ref"]["path"] == "/workspace/main.py"


@pytest.mark.asyncio
async def test_artifact_chart_creates_chart_gallery(client: AsyncClient) -> None:
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    await _emit(
        rt,
        "artifact.created",
        {"kind": "chart", "id": "art-1", "label": "p1"},
    )

    assert "chart_gallery" in await _open_kinds(client, sid)


@pytest.mark.asyncio
async def test_artifact_report_creates_report_tab(client: AsyncClient) -> None:
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    await _emit(
        rt,
        "artifact.created",
        {"kind": "report", "id": "art-1", "label": "summary.pdf"},
    )

    assert "report" in await _open_kinds(client, sid)


# ---- non-trigger events -----------------------------------------------


@pytest.mark.asyncio
async def test_tab_opened_event_does_not_loop(client: AsyncClient) -> None:
    """Handler must skip its own ``tab.*`` events to avoid a feedback loop."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    # Synthesise a tab.opened — the handler should ignore it. (Otherwise
    # this would deadlock or recurse via ensure_system_tab.)
    await _emit(
        rt,
        "tab.opened",
        {"id": "fake", "kind": "component", "title": "synthetic"},
    )
    # The two seeded tabs should be the only open ones.
    assert sorted(await _open_kinds(client, sid)) == ["files", "shell"]


@pytest.mark.asyncio
async def test_unrelated_event_does_not_spawn_anything(client: AsyncClient) -> None:
    """Events outside the configured prefix families are ignored."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    before = sorted(await _open_kinds(client, sid))
    # `metacognition.confidence` fires on every tool call but doesn't
    # have its own tab kind — so it should leave the manifest alone.
    await _emit(rt, "metacognition.confidence", {"confidence": 0.9})
    after = sorted(await _open_kinds(client, sid))
    assert before == after


@pytest.mark.asyncio
async def test_memory_event_spawns_memory_tab(client: AsyncClient) -> None:
    """First `memory.*` event spawns the cognitive Memory tab."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    assert "memory" not in await _open_kinds(client, sid)
    await _emit(rt, "memory.recalled", {"query": "x", "hits": 0})
    assert "memory" in await _open_kinds(client, sid)


@pytest.mark.asyncio
async def test_agent_event_spawns_agents_tab(client: AsyncClient) -> None:
    """First `agent.*` event spawns the cognitive Agents tab."""
    from polymath.runtime import get_runtime

    sid = (await client.post("/sessions")).json()["id"]
    rt = get_runtime(sid)

    assert "agents" not in await _open_kinds(client, sid)
    await _emit(
        rt,
        "agent.spawned",
        {"name": "analyst", "role": "research", "model": "openai:gpt-4.1"},
    )
    assert "agents" in await _open_kinds(client, sid)


# ---- handler robustness -----------------------------------------------


@pytest.mark.asyncio
async def test_handler_with_non_uuid_session_id_no_ops() -> None:
    """Defensive — non-UUID session id leaves the handler dormant."""
    from polymath.tab_respawn import make_respawn_handler

    handler = make_respawn_handler("not-a-uuid")
    # Should not raise.
    await handler(
        AgentEvent(
            event_type="shell.stdout",
            agent_name="test",
            timestamp=datetime.now(UTC),
            data={"line": "x"},
        )
    )


@pytest.mark.asyncio
async def test_handler_skips_editor_event_without_path() -> None:
    """Editor needs a path; absence is informational, not a respawn signal."""
    from polymath.tab_respawn import _extract_path

    evt = AgentEvent(
        event_type="tool.fs.write_file.started",
        agent_name="test",
        timestamp=datetime.now(UTC),
        data={"args": {}},
    )
    assert _extract_path(evt) is None
