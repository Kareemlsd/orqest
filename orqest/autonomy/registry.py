"""Central tool discovery and management.

The ToolRegistry provides a shared namespace for tools that agents and the
MetaOrchestrator can discover at runtime. Tools are registered by developers
or added dynamically; agents resolve ToolSpec names against this registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Tool


@dataclass
class ToolInfo:
    """Metadata about a registered tool."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Central registry of available tools.

    Agents and the MetaOrchestrator discover tools here.
    Tools can be pre-registered by developers or added dynamically.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._tools: dict[str, Tool] = {}
        self._info: dict[str, ToolInfo] = {}

    def register(self, tool: Tool, *, description: str | None = None) -> None:
        """Register a tool. Uses tool.name as the key."""
        name = tool.name
        self._tools[name] = tool
        self._info[name] = ToolInfo(
            name=name,
            description=description or getattr(tool, "description", ""),
        )

    def get(self, name: str) -> Tool | None:
        """Get a tool by name. Returns None if not found."""
        return self._tools.get(name)

    def search(self, query: str, *, k: int = 5) -> list[ToolInfo]:
        """Search tools by keyword matching in name and description."""
        query_lower = query.lower()
        matches: list[tuple[int, ToolInfo]] = []
        for info in self._info.values():
            score = 0
            if query_lower in info.name.lower():
                score += 2
            if query_lower in info.description.lower():
                score += 1
            if score > 0:
                matches.append((score, info))
        matches.sort(key=lambda x: x[0], reverse=True)
        return [info for _, info in matches[:k]]

    def list_all(self) -> list[ToolInfo]:
        """List all registered tools."""
        return list(self._info.values())

    def remove(self, name: str) -> None:
        """Remove a tool by name. No error if not found."""
        self._tools.pop(name, None)
        self._info.pop(name, None)

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Check whether a tool with the given name is registered."""
        return name in self._tools
