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
        transport: Connection transport — ``"stdio"``, ``"sse"``, or
            ``"streamable-http"``. ``"streamable-http"`` is the canonical
            transport for host↔container deployments (used by Tier-2
            :class:`DockerSandbox`); ``"sse"`` is the deprecated 2024-11-05
            transport (still supported for legacy MCP servers); ``"stdio"``
            launches the server as a subprocess.
        url: Server URL for ``"sse"`` and ``"streamable-http"`` transports.
            Ignored for stdio. For ``"streamable-http"`` should be the
            ``/mcp`` endpoint (e.g. ``http://127.0.0.1:8000/mcp``).
        headers: HTTP headers attached to every request. Used to carry
            session/auth tokens (e.g.
            ``{"Authorization": "Bearer <jwt>"}``). Empty for stdio.

    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPConfig:
    """Top-level MCP integration configuration.

    Args:
        servers: Explicit server configurations.
        auto_discover: Scan standard paths for MCP configs on connect.

    """

    servers: list[MCPServerConfig] = field(default_factory=list)
    auto_discover: bool = True
