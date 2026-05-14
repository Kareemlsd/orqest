"""Tests for online MCP server discovery."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from orqest.mcp.discovery import DiscoveredServer, MCPDiscovery


class TestDiscoveredServer:
    """DiscoveredServer data model and conversion."""

    def test_to_config_creates_sse_config(self) -> None:
        server = DiscoveredServer(
            name="sql-server",
            description="SQL database tools",
            url="https://mcp.example.com/sql",
            tools=["query", "insert"],
            source="registry",
        )
        config = server.to_config()
        assert config.name == "sql-server"
        assert config.transport == "sse"
        assert config.url == "https://mcp.example.com/sql"
        assert config.command == ""  # Not needed for SSE

    def test_default_fields(self) -> None:
        server = DiscoveredServer(
            name="test", description="desc", url="http://x"
        )
        assert server.tools == []
        assert server.source == "registry"
        assert server.metadata == {}


class TestMCPDiscovery:
    """MCPDiscovery searches registries and probes well-known URLs."""

    def test_init_default_registries(self) -> None:
        discovery = MCPDiscovery()
        assert len(discovery._registry_urls) >= 1

    def test_init_custom_registries(self) -> None:
        discovery = MCPDiscovery(registry_urls=["https://custom.reg/api"])
        assert discovery._registry_urls == ["https://custom.reg/api"]

    @pytest.mark.asyncio
    async def test_search_deduplicates_by_name(self) -> None:
        """Results from multiple registries are deduplicated."""
        discovery = MCPDiscovery(
            registry_urls=["https://reg1/api", "https://reg2/api"]
        )

        async def mock_query(url, query, max_results):
            return [
                DiscoveredServer(
                    name="shared-server",
                    description="Same server in both registries",
                    url="https://mcp.example.com",
                )
            ]

        with patch.object(discovery, "_query_registry", side_effect=mock_query):
            results = await discovery.search("database")
            assert len(results) == 1
            assert results[0].name == "shared-server"

    @pytest.mark.asyncio
    async def test_search_handles_registry_failure(self) -> None:
        """Failed registries are skipped gracefully."""
        discovery = MCPDiscovery(registry_urls=["https://broken.reg/api"])

        async def failing_query(url, query, max_results):
            raise ConnectionError("registry down")

        with patch.object(
            discovery, "_query_registry", side_effect=failing_query
        ):
            results = await discovery.search("anything")
            assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_max_results(self) -> None:
        discovery = MCPDiscovery(registry_urls=["https://reg/api"])

        async def many_results(url, query, max_results):
            return [
                DiscoveredServer(
                    name=f"server-{i}",
                    description=f"Server {i}",
                    url=f"https://s{i}.example.com",
                )
                for i in range(10)
            ]

        with patch.object(
            discovery, "_query_registry", side_effect=many_results
        ):
            results = await discovery.search("test", max_results=3)
            assert len(results) == 3

    @pytest.mark.asyncio
    async def test_probe_wellknown_returns_none_on_failure(self) -> None:
        discovery = MCPDiscovery()
        # Probe a non-existent URL — should return None, not raise
        result = await discovery.probe_wellknown("https://nonexistent.invalid")
        assert result is None

    @pytest.mark.asyncio
    async def test_query_registry_parses_list_format(self) -> None:
        """Registry returning a plain JSON list."""
        discovery = MCPDiscovery()

        response_data = [
            {
                "name": "github-mcp",
                "description": "GitHub tools",
                "url": "https://mcp.github.com",
                "tools": ["create_pr", "list_issues"],
            }
        ]

        import httpx

        mock_resp = httpx.Response(
            200,
            json=response_data,
            request=httpx.Request("GET", "https://registry.example.com"),
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await discovery._query_registry(
                "https://registry.example.com/api/search", "github", 5
            )
            assert len(results) == 1
            assert results[0].name == "github-mcp"
            assert "create_pr" in results[0].tools

    @pytest.mark.asyncio
    async def test_query_registry_parses_dict_format(self) -> None:
        """Registry returning ``{"results": [...]}``."""
        discovery = MCPDiscovery()

        response_data = {
            "results": [
                {
                    "name": "slack-mcp",
                    "description": "Slack integration",
                    "endpoint": "https://mcp.slack.com",
                    "tools": [{"name": "send_message"}],
                }
            ]
        }

        import httpx

        mock_resp = httpx.Response(
            200,
            json=response_data,
            request=httpx.Request("GET", "https://glama.ai/api/search"),
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await discovery._query_registry(
                "https://glama.ai/api/search", "slack", 5
            )
            assert len(results) == 1
            assert results[0].name == "slack-mcp"
            assert results[0].url == "https://mcp.slack.com"


class TestDiscoverAndConnect:
    """MCPServerManager.discover_and_connect integration."""

    @pytest.mark.asyncio
    async def test_discover_and_connect_returns_connections(self) -> None:
        from orqest.mcp.client import MCPServerManager
        from orqest.mcp.config import MCPConfig

        mgr = MCPServerManager(MCPConfig(auto_discover=False))

        # Mock discovery to return servers, mock connect to succeed
        mock_discovery = AsyncMock()
        mock_discovery.search.return_value = [
            DiscoveredServer(
                name="test-db",
                description="DB tools",
                url="https://db.mcp.example.com",
            )
        ]

        with (
            patch(
                "orqest.mcp.discovery.MCPDiscovery",
                return_value=mock_discovery,
            ),
            patch.object(
                mgr, "connect", side_effect=Exception("no real server")
            ),
        ):
            # connect will fail (no real server), but discover is called
            connections = await mgr.discover_and_connect("database SQL")
            assert connections == []  # All failed to connect
            mock_discovery.search.assert_awaited_once()


class TestSearchWiring:
    """search() merges registry results with configured well-known probes."""

    class _FakeDiscovery(MCPDiscovery):
        """Stubs the HTTP layer to test search() wiring without network."""

        async def _query_registry(self, registry_url, query, max_results):
            return [DiscoveredServer(
                name="reg-server", description="from registry", url="http://reg",
            )]

        async def probe_wellknown(self, base_url):
            return DiscoveredServer(
                name=f"wk-{base_url}", description="from well-known",
                url=base_url, source="wellknown",
            )

    @pytest.mark.asyncio
    async def test_search_merges_registry_and_wellknown(self) -> None:
        disc = self._FakeDiscovery(
            well_known_urls=["http://a.example", "http://b.example"]
        )
        results = await disc.search("anything", max_results=10)

        names = {s.name for s in results}
        assert names == {
            "reg-server", "wk-http://a.example", "wk-http://b.example",
        }
        assert {s.source for s in results} == {"registry", "wellknown"}

    @pytest.mark.asyncio
    async def test_search_without_wellknown_urls_is_registry_only(self) -> None:
        disc = self._FakeDiscovery()  # no well_known_urls configured
        results = await disc.search("anything")
        assert {s.source for s in results} == {"registry"}
