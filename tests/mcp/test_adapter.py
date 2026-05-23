"""Tests for MCP→pydantic-ai tool adapter."""

from __future__ import annotations

import pytest

from orqest.mcp.adapter import MCPToolAdapter, _extract_text


class _MockResult:
    """Simulates an MCP CallToolResult with content blocks."""

    def __init__(self, texts: list[str]) -> None:
        self.content = [type("Block", (), {"text": t})() for t in texts]


class _MockResultNoContent:
    """Simulates an MCP result without content attribute."""

    def __init__(self, val: str) -> None:
        self._val = val

    def __str__(self) -> str:
        return self._val


class TestExtractText:
    """_extract_text handles various MCP result shapes."""

    def test_single_block(self) -> None:
        assert _extract_text(_MockResult(["hello"])) == "hello"

    def test_multi_block(self) -> None:
        assert _extract_text(_MockResult(["a", "b"])) == "a\nb"

    def test_no_content_attr(self) -> None:
        assert _extract_text(_MockResultNoContent("fallback")) == "fallback"


class TestAdapt:
    """MCPToolAdapter.adapt creates a working pydantic-ai Tool."""

    @pytest.mark.asyncio
    async def test_creates_tool_with_name(self) -> None:
        async def call(name: str, args: dict) -> _MockResult:
            return _MockResult([f"result:{name}"])

        tool = MCPToolAdapter.adapt("greet", "Say hello", {}, call)
        assert tool.name == "greet"

    @pytest.mark.asyncio
    async def test_wrapper_returns_text(self) -> None:
        async def call(name: str, args: dict) -> _MockResult:
            return _MockResult([f"hi {args.get('who', 'world')}"])

        tool = MCPToolAdapter.adapt("greet", "Say hello", {}, call)
        # Call the underlying function directly
        fn = tool.function
        result = await fn(who="Alice")
        assert result == "hi Alice"

    @pytest.mark.asyncio
    async def test_wrapper_handles_error(self) -> None:
        async def call(name: str, args: dict) -> None:
            raise ConnectionError("server down")

        tool = MCPToolAdapter.adapt("broken", "Fails", {}, call)
        fn = tool.function
        result = await fn()
        assert "Error calling broken" in result

    @pytest.mark.asyncio
    async def test_adapt_many(self) -> None:
        async def call(name: str, args: dict) -> _MockResult:
            return _MockResult([name])

        defs = [
            {"name": "tool_a", "description": "A"},
            {"name": "tool_b", "description": "B"},
        ]
        tools = MCPToolAdapter.adapt_many(defs, call)
        assert len(tools) == 2
        assert tools[0].name == "tool_a"
        assert tools[1].name == "tool_b"

    @pytest.mark.asyncio
    async def test_adapt_many_skips_empty_name(self) -> None:
        async def call(name: str, args: dict) -> _MockResult:
            return _MockResult([name])

        defs = [{"name": ""}, {"name": "valid", "description": "ok"}]
        tools = MCPToolAdapter.adapt_many(defs, call)
        assert len(tools) == 1
        assert tools[0].name == "valid"
