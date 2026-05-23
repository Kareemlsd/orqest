"""Online MCP server discovery — find and connect to servers by capability.

Searches the MCP ecosystem for servers that provide specific tools or
capabilities, enabling agents to dynamically expand their toolset at
runtime without pre-configuration.

.. note::

   **Preview.** :meth:`MCPDiscovery.search` queries the configured
   registry endpoints and probes any configured ``well_known_urls`` for
   ``/.well-known/mcp.json`` manifests. What remains preview: the registry
   response-shape parsing is untested against live registries, and there
   is no web-search fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from orqest.mcp.config import MCPServerConfig


@dataclass
class DiscoveredServer:
    """A server found via online discovery.

    Attributes:
        name: Server identifier.
        description: What the server provides.
        url: Connection endpoint (SSE or Streamable HTTP).
        tools: Tool names advertised by the server.
        source: Where this was discovered ("registry", "wellknown", "search").
        metadata: Additional discovery metadata.

    """

    name: str
    description: str
    url: str
    tools: list[str] = field(default_factory=list)
    source: str = "registry"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_config(self) -> MCPServerConfig:
        """Convert to an MCPServerConfig for connection."""
        return MCPServerConfig(
            name=self.name,
            command="",  # Not needed for SSE/HTTP transport
            transport="sse",
            url=self.url,
        )


class MCPDiscovery:
    """Discover MCP servers online by querying registry endpoints.

    Enables agents to find tools they need at runtime without any
    pre-configuration. The MetaOrchestrator uses this when no local
    tool matches a subtask's requirements. Preview — see the module
    docstring for current limitations.

    Usage::

        discovery = MCPDiscovery()
        servers = await discovery.search("database SQL query")
        for server in servers:
            config = server.to_config()
            await manager.connect(config)

    """

    # Known registry/directory endpoints
    REGISTRY_SEARCH_URLS = [
        "https://registry.modelcontextprotocol.io/api/v1/search",
        "https://glama.ai/api/mcp/search",
    ]

    def __init__(
        self,
        *,
        registry_urls: list[str] | None = None,
        well_known_urls: list[str] | None = None,
        timeout: float = 15.0,
    ) -> None:
        """Initialize discovery.

        Args:
            registry_urls: Custom registry search endpoints.
                Defaults to the official MCP registry and Glama.
            well_known_urls: Base URLs to probe for ``/.well-known/mcp.json``
                manifests on every :meth:`search`. Empty by default.
            timeout: HTTP request timeout in seconds.

        """
        self._registry_urls = registry_urls or list(self.REGISTRY_SEARCH_URLS)
        self._well_known_urls = list(well_known_urls or [])
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> list[DiscoveredServer]:
        """Search for MCP servers matching a capability query.

        Probes any configured ``well_known_urls`` first (explicitly
        configured = highest intent), then queries the registry endpoints,
        deduplicating by server name.

        Args:
            query: Natural language description of needed capability
                (e.g., "SQL database queries", "GitHub repository access").
            max_results: Maximum servers to return.

        Returns:
            Discovered servers, well-known manifests ahead of registry hits.

        """
        all_servers: list[DiscoveredServer] = []
        seen_names: set[str] = set()

        # Explicitly-configured well-known manifests first — highest intent.
        for base_url in self._well_known_urls:
            try:
                server = await self.probe_wellknown(base_url)
            except Exception as exc:
                logger.debug(
                    "Well-known probe {url} failed: {err}", url=base_url, err=exc
                )
                continue
            if server is not None and server.name not in seen_names:
                seen_names.add(server.name)
                all_servers.append(server)

        # Then fuzzy registry search.
        for url in self._registry_urls:
            try:
                results = await self._query_registry(url, query, max_results)
                for server in results:
                    if server.name not in seen_names:
                        seen_names.add(server.name)
                        all_servers.append(server)
            except Exception as exc:
                logger.debug(
                    "Registry {url} query failed: {err}",
                    url=url,
                    err=exc,
                )

        return all_servers[:max_results]

    async def probe_wellknown(self, base_url: str) -> DiscoveredServer | None:
        """Probe a URL's ``/.well-known/mcp.json`` for server metadata.

        Args:
            base_url: The server's base URL (e.g., "https://mcp.example.com").

        Returns:
            A DiscoveredServer if the manifest exists, else None.

        """
        try:
            import httpx

            wellknown_url = f"{base_url.rstrip('/')}/.well-known/mcp.json"
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(wellknown_url)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                return DiscoveredServer(
                    name=data.get("name", base_url),
                    description=data.get("description", ""),
                    url=data.get("endpoint", base_url),
                    tools=[
                        t.get("name", "")
                        for t in data.get("tools", [])
                        if t.get("name")
                    ],
                    source="wellknown",
                    metadata=data,
                )
        except Exception as exc:
            logger.debug(
                "Well-known probe failed for {url}: {err}",
                url=base_url,
                err=exc,
            )
            return None

    async def _query_registry(
        self,
        registry_url: str,
        query: str,
        max_results: int,
    ) -> list[DiscoveredServer]:
        """Query a single registry endpoint."""
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                registry_url,
                params={"q": query, "limit": max_results},
            )
            resp.raise_for_status()
            data = resp.json()

            servers: list[DiscoveredServer] = []
            # Handle both list and dict-with-results formats
            items = data if isinstance(data, list) else data.get("results", data.get("servers", []))

            for item in items:
                if not isinstance(item, dict):
                    continue  # tolerate a malformed entry without losing the batch
                servers.append(
                    DiscoveredServer(
                        name=item.get("name", "unknown"),
                        description=item.get("description", ""),
                        url=item.get("url", item.get("endpoint", "")),
                        tools=[
                            t if isinstance(t, str) else t.get("name", "")
                            for t in item.get("tools", [])
                        ],
                        source="registry",
                        metadata=item,
                    )
                )
            return servers
