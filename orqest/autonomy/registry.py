"""Central tool discovery and management.

The ToolRegistry provides a shared namespace for tools that agents and the
MetaOrchestrator can discover at runtime. Tools are registered by developers
or added dynamically; agents resolve ToolSpec names against this registry.

When a tool name is missing, :meth:`ToolRegistry.get_or_discover` can
fall back to MCP discovery — finding a server that advertises the tool,
adapting its tools, and registering them. The flow is opt-in: consumers
must pass an explicit :class:`MCPDiscovery`, :class:`MCPServerManager`,
and :class:`PermissionGate`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai import Tool

if TYPE_CHECKING:
    from orqest.mcp.client import MCPServerManager
    from orqest.mcp.discovery import MCPDiscovery
    from orqest.mcp.permission import PermissionGate
    from orqest.observability.events import EventBus


async def _audit(
    bus: EventBus | None, event_type: str, data: dict[str, Any]
) -> None:
    """Emit a discovery audit event if a bus is supplied; otherwise no-op."""
    if bus is None:
        return
    try:
        from orqest.observability.events import AgentEvent

        await bus.emit(
            AgentEvent(event_type=event_type, agent_name="tool_registry", data=data)
        )
    except Exception:
        logger.debug("Discovery audit event {e} failed to emit", e=event_type)


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

    async def get_or_discover(
        self,
        name: str,
        *,
        discovery: MCPDiscovery | None = None,
        manager: MCPServerManager | None = None,
        permission: PermissionGate | None = None,
        audit_bus: EventBus | None = None,
        max_servers: int = 3,
    ) -> Tool | None:
        """Get a tool by name; if missing, fall back to MCP discovery.

        On a registry miss, searches for an MCP server advertising the
        tool, gates the request through ``permission`` (default
        :class:`DenyAll`), connects via ``manager``, and registers the
        discovered tools transparently. Returns the matching tool if
        found, otherwise ``None``.

        Audit-log events emitted via ``audit_bus`` (when supplied):

        * ``discovery.requested`` — a missing tool triggered discovery.
        * ``discovery.denied`` — :class:`PermissionGate` rejected the request.
        * ``discovery.connected`` — a discovered tool was registered (one per tool).
        * ``discovery.failed`` — search/connect raised.

        Args:
            name: Requested tool name.
            discovery: Optional :class:`MCPDiscovery`. If absent, returns ``None``.
            manager: Optional :class:`MCPServerManager` for connecting.
                If absent, returns ``None``.
            permission: Gate to require explicit approval. Default
                :class:`DenyAll` — discovery requires opt-in.
            audit_bus: Optional event bus for the audit trail.
            max_servers: Maximum number of discovered servers to try
                before giving up.
        """
        tool = self._tools.get(name)
        if tool is not None:
            return tool
        if discovery is None or manager is None:
            return None

        from orqest.mcp.permission import DenyAll

        gate: PermissionGate = permission or DenyAll()
        if not await gate.allow(name):
            await _audit(
                audit_bus,
                "discovery.denied",
                {"requested": name, "reason": "permission"},
            )
            return None

        await _audit(audit_bus, "discovery.requested", {"requested": name})
        try:
            servers = await discovery.search(name, max_results=max_servers)
        except Exception as exc:
            await _audit(
                audit_bus,
                "discovery.failed",
                {"requested": name, "stage": "search", "error": str(exc)[:200]},
            )
            return None

        for server in servers:
            try:
                conn = await manager.connect(server.to_config())
            except Exception as exc:
                await _audit(
                    audit_bus,
                    "discovery.failed",
                    {
                        "requested": name,
                        "server": server.name,
                        "stage": "connect",
                        "error": str(exc)[:200],
                    },
                )
                continue
            for t in conn.tools:
                self.register(t, description=getattr(t, "description", ""))
                await _audit(
                    audit_bus,
                    "discovery.connected",
                    {
                        "server": server.name,
                        "tool": t.name,
                        "source": getattr(server, "source", "unknown"),
                    },
                )
            if name in self._tools:
                return self._tools[name]
        return None

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
