"""Tests for ToolRegistry — tool discovery and management."""
from __future__ import annotations

from pydantic_ai import Tool

from orqest.autonomy.registry import ToolRegistry


def _make_tool(name: str, description: str = "") -> Tool:
    """Create a simple Tool for testing."""

    async def _fn(query: str) -> str:
        return query

    _fn.__name__ = name
    _fn.__qualname__ = name
    return Tool(_fn, name=name, description=description)


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = _make_tool("search", "Search the web")
        registry.register(tool, description="Search the web")
        assert registry.get("search") is tool

    def test_get_nonexistent_returns_none(self):
        registry = ToolRegistry()
        assert registry.get("missing") is None

    def test_search_by_name_keyword(self):
        registry = ToolRegistry()
        registry.register(_make_tool("web_search"), description="Find stuff online")
        registry.register(_make_tool("calculator"), description="Do math")
        results = registry.search("search")
        assert len(results) == 1
        assert results[0].name == "web_search"

    def test_search_by_description_keyword(self):
        registry = ToolRegistry()
        registry.register(_make_tool("fetcher"), description="Search the web for data")
        results = registry.search("search")
        assert len(results) == 1
        assert results[0].name == "fetcher"

    def test_search_returns_top_k(self):
        registry = ToolRegistry()
        for i in range(10):
            registry.register(
                _make_tool(f"tool_{i}"), description=f"Tool number {i}"
            )
        results = registry.search("tool", k=3)
        assert len(results) == 3

    def test_list_all(self):
        registry = ToolRegistry()
        registry.register(_make_tool("a"), description="Alpha")
        registry.register(_make_tool("b"), description="Beta")
        all_tools = registry.list_all()
        assert len(all_tools) == 2
        names = {t.name for t in all_tools}
        assert names == {"a", "b"}

    def test_remove(self):
        registry = ToolRegistry()
        registry.register(_make_tool("temp"), description="Temporary")
        assert "temp" in registry
        registry.remove("temp")
        assert "temp" not in registry
        assert registry.get("temp") is None

    def test_len_and_contains(self):
        registry = ToolRegistry()
        assert len(registry) == 0
        registry.register(_make_tool("x"), description="X tool")
        assert len(registry) == 1
        assert "x" in registry
        assert "y" not in registry

    def test_register_overwrites_existing(self):
        registry = ToolRegistry()
        registry.register(_make_tool("dup"), description="First version")
        registry.register(_make_tool("dup"), description="Second version")
        assert len(registry) == 1
        info = registry.list_all()[0]
        assert info.description == "Second version"
