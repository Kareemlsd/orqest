"""MCP integration for dynamic tool discovery and server exposure.

Provides MCPServerManager for connecting to MCP servers and using their
tools as pydantic-ai tools, MCPToolAdapter for bridging MCP→pydantic-ai,
and create_orqest_server for exposing Orqest as an MCP server.
"""

from orqest.mcp.adapter import MCPToolAdapter
from orqest.mcp.client import MCPConnection, MCPServerManager
from orqest.mcp.config import MCPConfig, MCPServerConfig
from orqest.mcp.discovery import DiscoveredServer, MCPDiscovery

__all__ = [
    "DiscoveredServer",
    "MCPConfig",
    "MCPConnection",
    "MCPDiscovery",
    "MCPServerConfig",
    "MCPServerManager",
    "MCPToolAdapter",
]
