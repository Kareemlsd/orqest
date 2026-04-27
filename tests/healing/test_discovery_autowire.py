"""Tests for the MCP auto-discovery flow:
ToolRegistry.get_or_discover + DiscoveryHook + PermissionGate.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import Tool

from orqest.autonomy.registry import ToolRegistry
from orqest.hooks import Continue, HookRunner, Redirect
from orqest.mcp import (
    AllowAll,
    AllowList,
    DenyAll,
    DiscoveryHook,
    PermissionGate,
)
from orqest.mcp.discovery import DiscoveredServer
from orqest.observability.events import AgentEvent, EventBus


# ---- Fixtures ---------------------------------------------------------


def _make_tool(name: str, description: str = "") -> Tool:
    async def _fn() -> str:
        return f"called:{name}"

    return Tool(_fn, name=name, description=description)


class _StubDiscovery:
    """Minimal MCPDiscovery substitute."""

    def __init__(self, servers: list[DiscoveredServer]) -> None:
        self._servers = servers
        self.calls: list[str] = []

    async def search(self, query: str, max_results: int = 5) -> list[DiscoveredServer]:
        self.calls.append(query)
        return self._servers[:max_results]


class _StubConnection:
    def __init__(self, tools: list[Tool]) -> None:
        self.tools = tools


class _StubManager:
    """Minimal MCPServerManager substitute."""

    def __init__(self, server_to_tools: dict[str, list[Tool]]) -> None:
        self._map = server_to_tools
        self.connect_calls: list[str] = []
        self.fail_on: set[str] = set()

    async def connect(self, config: Any) -> _StubConnection:
        self.connect_calls.append(config.name)
        if config.name in self.fail_on:
            raise RuntimeError(f"connect failure for {config.name}")
        return _StubConnection(self._map.get(config.name, []))


# ---- PermissionGate ---------------------------------------------------


@pytest.mark.asyncio
async def test_permission_gates_satisfy_protocol():
    for gate in [AllowAll(), DenyAll(), AllowList(["foo"])]:
        assert isinstance(gate, PermissionGate)


@pytest.mark.asyncio
async def test_allow_all_permits_anything():
    gate = AllowAll()
    assert await gate.allow("anything") is True


@pytest.mark.asyncio
async def test_deny_all_rejects_anything():
    gate = DenyAll()
    assert await gate.allow("anything") is False


@pytest.mark.asyncio
async def test_allow_list_regex_match():
    gate = AllowList([r"^safe_", r"^read_only_"])
    assert await gate.allow("safe_search") is True
    assert await gate.allow("read_only_db") is True
    assert await gate.allow("rm_rf") is False


# ---- ToolRegistry.get_or_discover ------------------------------------


@pytest.mark.asyncio
async def test_get_or_discover_returns_existing_tool_without_discovery():
    reg = ToolRegistry()
    reg.register(_make_tool("existing"))
    discovery = _StubDiscovery([])  # Empty — should not be consulted.
    result = await reg.get_or_discover(
        "existing",
        discovery=discovery,  # type: ignore[arg-type]
        manager=_StubManager({}),  # type: ignore[arg-type]
        permission=AllowAll(),
    )
    assert result is not None
    assert discovery.calls == []  # discovery never invoked


@pytest.mark.asyncio
async def test_get_or_discover_returns_none_without_discovery_obj():
    reg = ToolRegistry()
    result = await reg.get_or_discover("missing")
    assert result is None


@pytest.mark.asyncio
async def test_get_or_discover_calls_discovery_and_registers():
    server = DiscoveredServer(
        name="search_server", description="d", url="http://example", tools=["search"]
    )
    reg = ToolRegistry()
    discovery = _StubDiscovery([server])
    manager = _StubManager({"search_server": [_make_tool("search")]})
    result = await reg.get_or_discover(
        "search",
        discovery=discovery,  # type: ignore[arg-type]
        manager=manager,  # type: ignore[arg-type]
        permission=AllowAll(),
    )
    assert result is not None
    assert discovery.calls == ["search"]
    assert "search" in reg


@pytest.mark.asyncio
async def test_get_or_discover_default_deny_returns_none():
    server = DiscoveredServer(name="s", description="d", url="u", tools=["search"])
    reg = ToolRegistry()
    discovery = _StubDiscovery([server])
    manager = _StubManager({"s": [_make_tool("search")]})
    # No permission supplied → DenyAll default.
    result = await reg.get_or_discover(
        "search",
        discovery=discovery,  # type: ignore[arg-type]
        manager=manager,  # type: ignore[arg-type]
    )
    assert result is None
    assert discovery.calls == []  # discovery not called when denied


@pytest.mark.asyncio
async def test_get_or_discover_tries_next_server_on_connect_failure():
    s1 = DiscoveredServer(name="bad", description="d", url="u1", tools=["x"])
    s2 = DiscoveredServer(name="good", description="d", url="u2", tools=["x"])
    reg = ToolRegistry()
    discovery = _StubDiscovery([s1, s2])
    manager = _StubManager({"good": [_make_tool("x")]})
    manager.fail_on.add("bad")
    result = await reg.get_or_discover(
        "x",
        discovery=discovery,  # type: ignore[arg-type]
        manager=manager,  # type: ignore[arg-type]
        permission=AllowAll(),
    )
    assert result is not None
    assert manager.connect_calls == ["bad", "good"]


@pytest.mark.asyncio
async def test_get_or_discover_no_servers_returns_none():
    reg = ToolRegistry()
    discovery = _StubDiscovery([])
    manager = _StubManager({})
    result = await reg.get_or_discover(
        "missing",
        discovery=discovery,  # type: ignore[arg-type]
        manager=manager,  # type: ignore[arg-type]
        permission=AllowAll(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_get_or_discover_emits_audit_events():
    bus = EventBus()
    captured: list[AgentEvent] = []
    for et in ("discovery.requested", "discovery.connected", "discovery.denied", "discovery.failed"):
        bus.subscribe(et, lambda e, _captured=captured: _captured.append(e))

    server = DiscoveredServer(name="s", description="d", url="u", tools=["t"])
    reg = ToolRegistry()
    await reg.get_or_discover(
        "t",
        discovery=_StubDiscovery([server]),  # type: ignore[arg-type]
        manager=_StubManager({"s": [_make_tool("t")]}),  # type: ignore[arg-type]
        permission=AllowAll(),
        audit_bus=bus,
    )

    types_emitted = [e.event_type for e in captured]
    assert "discovery.requested" in types_emitted
    assert "discovery.connected" in types_emitted


@pytest.mark.asyncio
async def test_get_or_discover_emits_denied_when_gate_rejects():
    bus = EventBus()
    captured: list[AgentEvent] = []
    bus.subscribe("discovery.denied", lambda e: captured.append(e))

    reg = ToolRegistry()
    await reg.get_or_discover(
        "missing",
        discovery=_StubDiscovery([]),  # type: ignore[arg-type]
        manager=_StubManager({}),  # type: ignore[arg-type]
        permission=DenyAll(),
        audit_bus=bus,
    )
    assert len(captured) == 1
    assert captured[0].data["reason"] == "permission"


# ---- DiscoveryHook ----------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_hook_continues_for_non_tool_not_found_error():
    hook = DiscoveryHook(
        ToolRegistry(),  # type: ignore[arg-type]
        _StubDiscovery([]),  # type: ignore[arg-type]
        _StubManager({}),  # type: ignore[arg-type]
    )
    decision = await hook.on_error("t", {}, RuntimeError("connection refused"), None)
    assert isinstance(decision, Continue)


@pytest.mark.asyncio
async def test_discovery_hook_redirects_after_successful_discovery():
    server = DiscoveredServer(name="s", description="d", url="u", tools=["search"])
    reg = ToolRegistry()
    discovery = _StubDiscovery([server])
    manager = _StubManager({"s": [_make_tool("search")]})
    hook = DiscoveryHook(
        reg, discovery, manager, permission=AllowAll(),  # type: ignore[arg-type]
    )
    decision = await hook.on_error(
        "search", {}, RuntimeError("tool not found: search"), None
    )
    assert isinstance(decision, Redirect)
    assert decision.new_tool == "search"


@pytest.mark.asyncio
async def test_discovery_hook_continues_when_permission_denies():
    server = DiscoveredServer(name="s", description="d", url="u", tools=["search"])
    reg = ToolRegistry()
    hook = DiscoveryHook(
        reg,
        _StubDiscovery([server]),  # type: ignore[arg-type]
        _StubManager({"s": [_make_tool("search")]}),  # type: ignore[arg-type]
        permission=DenyAll(),
    )
    decision = await hook.on_error(
        "search", {}, RuntimeError("tool not found"), None
    )
    assert isinstance(decision, Continue)


@pytest.mark.asyncio
async def test_discovery_hook_continues_when_discovery_fails():
    class _CrashyDiscovery:
        async def search(self, *a, **kw):
            raise RuntimeError("network down")

    hook = DiscoveryHook(
        ToolRegistry(),
        _CrashyDiscovery(),  # type: ignore[arg-type]
        _StubManager({}),  # type: ignore[arg-type]
        permission=AllowAll(),
    )
    decision = await hook.on_error(
        "x", {}, RuntimeError("tool not found"), None
    )
    assert isinstance(decision, Continue)


@pytest.mark.asyncio
async def test_discovery_hook_works_through_hook_runner():
    """End-to-end: HookRunner + DiscoveryHook on `tool.error` → Redirect."""
    server = DiscoveredServer(name="s", description="d", url="u", tools=["browse"])
    reg = ToolRegistry()
    hook = DiscoveryHook(
        reg,
        _StubDiscovery([server]),  # type: ignore[arg-type]
        _StubManager({"s": [_make_tool("browse")]}),  # type: ignore[arg-type]
        permission=AllowAll(),
    )
    runner = HookRunner([hook])
    decision = await runner.run_error(
        "browse", {}, RuntimeError("no tool named browse"), None
    )
    assert isinstance(decision, Redirect)
    assert decision.new_tool == "browse"
