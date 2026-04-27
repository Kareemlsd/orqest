"""MCP integration for dynamic tool discovery and server exposure.

Provides MCPServerManager for connecting to MCP servers and using their
tools as pydantic-ai tools, MCPToolAdapter for bridging MCP→pydantic-ai,
and create_orqest_server for exposing Orqest as an MCP server.

Auto-discovery is gated by :class:`PermissionGate` (default
:class:`DenyAll`); two integration paths are available:

* :meth:`ToolRegistry.get_or_discover` — *deliberate* lookup (called
  by code that knows it needs a tool now).
* :class:`DiscoveryHook` — *opportunistic* recovery from runtime
  "tool not found" errors raised by hallucinating LLMs.
"""

from orqest.mcp.adapter import MCPToolAdapter
from orqest.mcp.client import MCPConnection, MCPServerManager
from orqest.mcp.config import MCPConfig, MCPServerConfig
from orqest.mcp.discovery import DiscoveredServer, MCPDiscovery
from orqest.mcp.discovery_hook import DiscoveryHook
from orqest.mcp.permission import AllowAll, AllowList, DenyAll, PermissionGate

__all__ = [
    "AllowAll",
    "AllowList",
    "DenyAll",
    "DiscoveredServer",
    "DiscoveryHook",
    "MCPConfig",
    "MCPConnection",
    "MCPDiscovery",
    "MCPServerConfig",
    "MCPServerManager",
    "MCPToolAdapter",
    "PermissionGate",
]
