"""MCP client — connect to servers, discover tools, manage lifecycles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic_ai import Tool

from orqest.mcp.adapter import MCPToolAdapter
from orqest.mcp.config import MCPConfig, MCPServerConfig


class MCPConnection:
    """A live connection to a single MCP server.

    Manages the transport, session, and adapted tool list for one server.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        """Initialize with server config. Call ``connect()`` to start."""
        self.config = config
        self.name = config.name
        self._session: Any = None
        self._client_ctx: Any = None
        self._session_ctx: Any = None
        self._tools: list[Tool] = []
        self._connected = False

    async def connect(self) -> None:
        """Establish the MCP connection and discover tools.

        Branches on ``config.transport``: ``"stdio"`` launches the server
        process via ``stdio_client``; ``"sse"`` connects to ``config.url``
        via ``sse_client``. Both transports yield a ``(read, write)`` pair
        that drives an identical ``ClientSession`` lifecycle.
        """
        from mcp import ClientSession

        self._client_ctx = self._open_transport()
        read, write = await self._client_ctx.__aenter__()

        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()

        result = await self._session.list_tools()
        self._tools = MCPToolAdapter.adapt_many(
            [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema,
                }
                for t in result.tools
            ],
            call_fn=self._call_tool,
        )
        self._connected = True
        logger.info(
            "Connected to MCP server '{name}' — {n} tools",
            name=self.name,
            n=len(self._tools),
        )

    def _open_transport(self) -> Any:
        """Build the transport context manager for this server's config.

        ``stdio`` launches the configured command; ``sse`` connects to
        ``config.url``. Both return an async context manager yielding a
        ``(read, write)`` stream pair.

        Raises:
            ValueError: Unknown transport, or an ``sse`` config with no url.

        """
        transport = self.config.transport
        if transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            return stdio_client(
                StdioServerParameters(
                    command=self.config.command,
                    args=self.config.args,
                    env=self.config.env or None,
                )
            )
        if transport == "sse":
            if not self.config.url:
                raise ValueError(
                    f"MCP server '{self.name}' uses sse transport but has no url"
                )
            from mcp.client.sse import sse_client

            return sse_client(self.config.url)
        raise ValueError(
            f"MCP server '{self.name}' has unknown transport {transport!r} "
            "(expected 'stdio' or 'sse')"
        )

    async def disconnect(self) -> None:
        """Close the connection gracefully."""
        try:
            if self._session_ctx:
                await self._session_ctx.__aexit__(None, None, None)
            if self._client_ctx:
                await self._client_ctx.__aexit__(None, None, None)
        except Exception as exc:
            logger.debug(
                "Error disconnecting from {name}: {err}",
                name=self.name,
                err=exc,
            )
        finally:
            self._connected = False
            self._session = None
            self._tools = []

    async def _call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Call a tool on the connected MCP server."""
        if not self._session:
            raise RuntimeError(
                f"Not connected to MCP server '{self.name}'"
            )
        return await self._session.call_tool(
            tool_name, arguments=arguments
        )

    @property
    def tools(self) -> list[Tool]:
        """All tools from this server."""
        return list(self._tools)

    @property
    def connected(self) -> bool:
        """Whether the connection is alive."""
        return self._connected

    @property
    def tool_names(self) -> list[str]:
        """Names of all available tools."""
        return [t.name for t in self._tools]


class MCPServerManager:
    """Manage connections to multiple MCP servers.

    Handles lifecycle, auto-discovery from standard config paths, and
    provides a unified tool list across all connected servers.  Supports
    ``async with`` for automatic cleanup.
    """

    def __init__(self, config: MCPConfig | None = None) -> None:
        """Initialize the manager.

        Args:
            config: Explicit MCP configuration.  When *auto_discover* is
                ``True`` (the default), standard config paths are also
                scanned on ``connect_all()``.

        """
        self._config = config or MCPConfig()
        self._connections: dict[str, MCPConnection] = {}

    # -- lifecycle ---------------------------------------------------------

    async def connect_all(self) -> None:
        """Connect to all configured + discovered servers."""
        configs = list(self._config.servers)
        if self._config.auto_discover:
            configs.extend(self.discover_local_configs())
        for cfg in configs:
            try:
                await self.connect(cfg)
            except Exception:
                pass  # logged inside connect()

    async def connect(self, config: MCPServerConfig) -> MCPConnection:
        """Connect to a single MCP server.

        Raises:
            Exception: Propagated from the transport layer on failure.

        """
        conn = MCPConnection(config)
        try:
            await conn.connect()
            self._connections[config.name] = conn
            return conn
        except Exception as exc:
            logger.warning(
                "Failed to connect to MCP server '{name}': {err}",
                name=config.name,
                err=exc,
            )
            raise

    async def disconnect_all(self) -> None:
        """Disconnect from every server."""
        for conn in self._connections.values():
            await conn.disconnect()
        self._connections.clear()

    async def disconnect(self, name: str) -> None:
        """Disconnect from a specific server by name."""
        conn = self._connections.pop(name, None)
        if conn:
            await conn.disconnect()

    # -- online discovery --------------------------------------------------

    async def discover_and_connect(
        self,
        query: str,
        *,
        max_servers: int = 3,
    ) -> list[MCPConnection]:
        """Search online for MCP servers matching a capability and connect.

        Uses ``MCPDiscovery`` to find servers by keyword, then connects
        to each. This is the key method that enables agents to
        dynamically expand their toolset at runtime.

        Args:
            query: Capability description (e.g., "SQL database", "GitHub").
            max_servers: Maximum number of servers to connect to.

        Returns:
            List of newly established connections.

        """
        from orqest.mcp.discovery import MCPDiscovery

        discovery = MCPDiscovery()
        discovered = await discovery.search(query, max_results=max_servers)

        new_connections: list[MCPConnection] = []
        for server in discovered:
            if server.name in self._connections:
                continue  # Already connected
            try:
                config = server.to_config()
                conn = await self.connect(config)
                new_connections.append(conn)
                logger.info(
                    "Discovered and connected to '{name}' for '{q}'",
                    name=server.name,
                    q=query,
                )
            except Exception:
                pass  # Logged inside connect()

        return new_connections

    # -- tool access -------------------------------------------------------

    def get_all_tools(self) -> list[Tool]:
        """Collect tools from all live connections."""
        tools: list[Tool] = []
        for conn in self._connections.values():
            if conn.connected:
                tools.extend(conn.tools)
        return tools

    def get_tools(self, server_name: str) -> list[Tool]:
        """Get tools from one server."""
        conn = self._connections.get(server_name)
        if conn and conn.connected:
            return conn.tools
        return []

    def search_tools(self, query: str) -> list[Tool]:
        """Keyword search across all connected servers."""
        q = query.lower()
        return [
            t
            for t in self.get_all_tools()
            if q in t.name.lower()
            or q in (getattr(t, "description", "") or "").lower()
        ]

    # -- properties --------------------------------------------------------

    @property
    def connected_servers(self) -> list[str]:
        """Names of all live connections."""
        return [n for n, c in self._connections.items() if c.connected]

    @property
    def total_tools(self) -> int:
        """Total tools across all connections."""
        return len(self.get_all_tools())

    # -- discovery ---------------------------------------------------------

    @staticmethod
    def discover_local_configs() -> list[MCPServerConfig]:
        """Scan standard paths for MCP server configurations.

        Checks ``~/.claude.json``, ``~/.claude/claude.json``, and
        ``~/.config/Claude/claude_desktop_config.json``.
        """
        configs: list[MCPServerConfig] = []
        seen_names: set[str] = set()
        search_paths = [
            Path.home() / ".claude.json",
            Path.home() / ".claude" / "claude.json",
            Path.home() / ".config" / "Claude" / "claude_desktop_config.json",
        ]
        for path in search_paths:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
                for name, defn in data.get("mcpServers", {}).items():
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                    configs.append(
                        MCPServerConfig(
                            name=name,
                            command=defn.get("command", ""),
                            args=defn.get("args", []),
                            env=defn.get("env", {}),
                        )
                    )
                if configs:
                    logger.debug(
                        "Discovered {n} MCP servers from {p}",
                        n=len(configs),
                        p=path,
                    )
            except Exception as exc:
                logger.debug(
                    "Could not read {p}: {e}", p=path, e=exc
                )
        return configs

    # -- context manager ---------------------------------------------------

    async def __aenter__(self) -> MCPServerManager:
        await self.connect_all()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect_all()
