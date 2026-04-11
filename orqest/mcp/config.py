"""Configuration for MCP server connections."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for a single MCP server connection.

    Args:
        name: Human-readable identifier for this server.
        command: Executable to launch (e.g., "python", "node", "npx").
        args: Command-line arguments (e.g., ["-m", "my_mcp_server"]).
        env: Environment variables passed to the server process.
        transport: Connection transport — "stdio" or "sse".
        url: Server URL for SSE transport. Ignored for stdio.

    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    url: str | None = None


@dataclass(frozen=True)
class MCPConfig:
    """Top-level MCP integration configuration.

    Args:
        servers: Explicit server configurations.
        auto_discover: Scan standard paths for MCP configs on connect.
        connection_timeout: Seconds to wait for a server to respond.

    """

    servers: list[MCPServerConfig] = field(default_factory=list)
    auto_discover: bool = True
    connection_timeout: float = 30.0
