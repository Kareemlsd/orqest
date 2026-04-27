"""Tests for the generative-UI manifest endpoints.

After the Phase β consolidation the backend exposes two endpoints
(``/sessions/{sid}/ui/event-types`` and
``/sessions/{sid}/ui/component-types``) so the frontend can self-
configure its SSE listener whitelist and component resolver against
the backend's source of truth instead of duplicating a hard-coded
manifest.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_event_types_includes_static_set(client: AsyncClient) -> None:
    """The static base whitelist (legacy events) is included in the response."""
    sid = (await client.post("/sessions")).json()["id"]
    r = await client.get(f"/sessions/{sid}/ui/event-types")
    assert r.status_code == 200
    body = r.json()
    types = set(body["event_types"])

    # A representative slice of the legacy whitelist Polymath uses today.
    must_contain = {
        "heartbeat",
        "plan.init",
        "plan.task.updated",
        "tool.before",
        "tool.after",
        "tool.error",
        "metacognition.confidence",
        "agent.spawned",
        "agent.completed",
        "takeover.activated",
        "takeover.released",
        "shell.stdout",
        "shell.exit",
        "browser.action",
        "artifact.created",
        "tool.web_search.started",
        "tool.web_search.completed",
        "tool.web_fetch.started",
        "tool.web_fetch.completed",
    }
    assert must_contain <= types


@pytest.mark.asyncio
async def test_event_types_includes_dynamic_ui_types(
    client: AsyncClient,
) -> None:
    """Each first-party UI component contributes its init/delta/remove triplet."""
    sid = (await client.post("/sessions")).json()["id"]
    r = await client.get(f"/sessions/{sid}/ui/event-types")
    assert r.status_code == 200
    types = set(r.json()["event_types"])

    # Workbench is constructed with ``default_registry()`` which preloads
    # the five first-party components.
    for component_type in ("plan", "chart", "table", "form", "takeover_dialog"):
        assert f"ui.{component_type}.init" in types, component_type
        assert f"ui.{component_type}.delta" in types, component_type
        assert f"ui.{component_type}.remove" in types, component_type


@pytest.mark.asyncio
async def test_component_types_lists_first_party(
    client: AsyncClient,
) -> None:
    """The component-types endpoint exposes the registered discriminators."""
    sid = (await client.post("/sessions")).json()["id"]
    r = await client.get(f"/sessions/{sid}/ui/component-types")
    assert r.status_code == 200
    component_types = set(r.json()["component_types"])
    # Auto-registered first-party catalog from ``default_registry()``.
    assert {"chart", "form", "plan", "table", "takeover_dialog"} <= component_types
