"""DiscoveryHook — opportunistic auto-discovery on tool-not-found errors.

A :class:`ToolHook` that intercepts ``on_error`` events whose error
suggests a missing tool, asks :class:`ToolRegistry` to discover and
register the tool, then returns :class:`Redirect` so the caller retries
the original call. Pairs with :meth:`ToolRegistry.get_or_discover` —
the latter is the *deliberate* path (called by code that knows it
needs a tool now); the hook is the *opportunistic* safety net.

Both paths route through the same :class:`PermissionGate`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orqest.hooks import Continue, HookDecision, Redirect

if TYPE_CHECKING:
    from orqest.autonomy.registry import ToolRegistry
    from orqest.mcp.client import MCPServerManager
    from orqest.mcp.discovery import MCPDiscovery
    from orqest.mcp.permission import PermissionGate
    from orqest.observability.events import EventBus


def _is_tool_not_found(error: Exception) -> bool:
    """Heuristic — error string suggests a missing tool name.

    Different SDKs (pydantic-AI, LangChain, etc.) raise different
    exception types with overlapping message conventions. We match
    string fragments commonly used to describe missing tools.
    """
    msg = str(error).lower()
    return any(
        marker in msg
        for marker in (
            "tool not found",
            "no tool named",
            "unknown tool",
            "tool does not exist",
            "no such tool",
        )
    )


class DiscoveryHook:
    """ToolHook that recovers from "tool not found" via MCP discovery.

    The hook's :meth:`on_error` returns :class:`Redirect(new_tool=name)`
    after the tool is registered (caller should retry with the registered
    tool), or :class:`Continue` otherwise — including when the gate denies
    or discovery fails.
    """

    def __init__(
        self,
        registry: "ToolRegistry",
        discovery: "MCPDiscovery",
        manager: "MCPServerManager",
        *,
        permission: "PermissionGate | None" = None,
        audit_bus: "EventBus | None" = None,
    ) -> None:
        self._registry = registry
        self._discovery = discovery
        self._manager = manager
        self._permission = permission
        self._audit_bus = audit_bus

    async def on_error(
        self,
        tool_name: str,
        args: dict[str, Any],
        error: Exception,
        state: Any,
    ) -> HookDecision:
        if not _is_tool_not_found(error):
            return Continue()
        tool = await self._registry.get_or_discover(
            tool_name,
            discovery=self._discovery,
            manager=self._manager,
            permission=self._permission,
            audit_bus=self._audit_bus,
        )
        if tool is None:
            return Continue()
        return Redirect(new_tool=tool_name, reason="discovered via MCP")
