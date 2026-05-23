"""Tests for orqest.sandbox.docker_runtime.server.build_server.

Tests construct the FastMCP server in-process (no HTTP transport,
no Docker, no real subprocess where avoidable) and exercise the
built-in tools' logic + the persisted-tool replay path.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from orqest.sandbox.docker_runtime.executor import Executor, ExecutorConfig
from orqest.sandbox.docker_runtime.server import build_server
from orqest.sandbox.docker_runtime.store import ToolStore

_uv_available = shutil.which("uv") is not None
_skip_if_no_uv = pytest.mark.skipif(
    not _uv_available, reason="uv binary not on PATH; skipping server tests"
)


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def store():
    s = ToolStore(":memory:")
    yield s
    s.close()


@pytest.fixture
def executor(workspace):
    return Executor(ExecutorConfig(
        workspace_root=workspace,
        session_id="test-session",
        allowed_packages=frozenset(),
    ))


# --- Server construction ---------------------------------------------------


def test_build_server_registers_four_builtin_tools(executor, store):
    import asyncio

    mcp = build_server(executor=executor, store=store, middleware=None)
    tools = asyncio.run(mcp.get_tools())
    assert set(tools.keys()) == {
        "execute_python",
        "promote_tool",
        "list_persisted_tools",
        "forget_tool",
    }


def test_build_server_replays_persisted_tools_at_startup(executor, store):
    """Tools already in SQLite should be added to the MCP registry on construction."""
    import asyncio

    store.persist(
        name="extract_dois",
        description="Extract DOIs from text",
        parameters={"text": {"type": "string"}},
        implementation="return []",
        allowed_imports=["re"],
    )
    mcp = build_server(executor=executor, store=store, middleware=None)
    tools = asyncio.run(mcp.get_tools())
    assert "extract_dois" in tools
    # Plus the four built-ins
    assert len(tools) == 5


# --- promote_tool round-trip ----------------------------------------------


@pytest.mark.asyncio
async def test_promote_tool_persists_and_registers(executor, store):
    mcp = build_server(executor=executor, store=store, middleware=None)
    tools_before = await mcp.get_tools()
    assert "extract_dois" not in tools_before

    promote_tool = (await mcp.get_tools())["promote_tool"]
    result = await promote_tool.run({
        "name": "extract_dois",
        "description": "Extract DOIs from text",
        "parameters": {"text": {"type": "string"}},
        "implementation": "return []",
        "allowed_imports": ["re"],
        "dependencies": [],
    })
    # FastMCP wraps tool returns; extract from structured_content
    payload = result.structured_content if hasattr(result, "structured_content") else result
    assert payload["name"] == "extract_dois"
    assert payload["version"] == 1

    # Now visible in the MCP registry
    tools_after = await mcp.get_tools()
    assert "extract_dois" in tools_after

    # And in the SQLite store
    persisted = store.get("extract_dois")
    assert persisted is not None
    assert persisted.version == 1


@pytest.mark.asyncio
async def test_list_persisted_tools_enumerates_store(executor, store):
    store.persist(
        name="a", description="a", parameters={},
        implementation="return 1", allowed_imports=[],
    )
    store.persist(
        name="b", description="b", parameters={},
        implementation="return 2", allowed_imports=[],
    )
    mcp = build_server(executor=executor, store=store, middleware=None)
    tools = await mcp.get_tools()
    list_tool = tools["list_persisted_tools"]
    result = await list_tool.run({})
    payload = result.structured_content if hasattr(result, "structured_content") else result
    # FastMCP may wrap list returns under 'result' key
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]
    assert isinstance(payload, list)
    names = {entry["name"] for entry in payload}
    assert names == {"a", "b"}


@pytest.mark.asyncio
async def test_forget_tool_removes_from_store(executor, store):
    store.persist(
        name="x", description="x", parameters={},
        implementation="return 1", allowed_imports=[],
    )
    mcp = build_server(executor=executor, store=store, middleware=None)
    forget_tool = (await mcp.get_tools())["forget_tool"]
    result = await forget_tool.run({"name": "x"})
    payload = result.structured_content if hasattr(result, "structured_content") else result
    assert payload["deleted"] == 1
    assert store.get("x") is None


# --- execute_python round-trip --------------------------------------------


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_execute_python_runs_safe_arithmetic(executor, store):
    mcp = build_server(executor=executor, store=store, middleware=None)
    execute = (await mcp.get_tools())["execute_python"]
    result = await execute.run({
        "code": "return args['x'] + args['y']",
        "agent_id": "alice",
        "args": {"x": 3, "y": 4},
        "allowed_imports": [],
        "timeout_s": 10.0,
    })
    payload = result.structured_content if hasattr(result, "structured_content") else result
    assert payload["success"] is True
    assert payload["output"] == 7


# --- Threshold promotion --------------------------------------------------


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_threshold_promotion_fires_after_n_invocations(executor, store):
    """Successful invocations of the same code+name should auto-promote
    after promotion_threshold."""
    mcp = build_server(
        executor=executor,
        store=store,
        middleware=None,
        promotion_policy="threshold",
        promotion_threshold=3,
    )
    execute = (await mcp.get_tools())["execute_python"]

    # Verify not promoted before threshold
    for i in range(2):
        result = await execute.run({
            "code": "return 42",
            "agent_id": "alice",
            "args": {},
            "allowed_imports": [],
            "tool_name": "constant_42",
            "timeout_s": 10.0,
        })
        payload = result.structured_content if hasattr(result, "structured_content") else result
        assert payload["success"] is True
    assert store.get("constant_42") is None

    # Third invocation should trigger promotion
    await execute.run({
        "code": "return 42",
        "agent_id": "alice",
        "args": {},
        "allowed_imports": [],
        "tool_name": "constant_42",
        "timeout_s": 10.0,
    })
    persisted = store.get("constant_42")
    assert persisted is not None
    assert persisted.version == 1
