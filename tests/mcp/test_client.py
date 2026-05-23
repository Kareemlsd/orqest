"""Tests for MCPServerManager (unit tests — no real MCP servers)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orqest.mcp.client import MCPConnection, MCPServerManager
from orqest.mcp.config import MCPConfig, MCPServerConfig


class TestMCPServerManager:
    """Unit tests for manager state and local config discovery."""

    def test_init_empty(self) -> None:
        mgr = MCPServerManager()
        assert mgr.connected_servers == []
        assert mgr.total_tools == 0

    def test_get_all_tools_empty(self) -> None:
        mgr = MCPServerManager()
        assert mgr.get_all_tools() == []

    def test_get_tools_unknown_server(self) -> None:
        mgr = MCPServerManager()
        assert mgr.get_tools("nonexistent") == []

    def test_search_tools_empty(self) -> None:
        mgr = MCPServerManager()
        assert mgr.search_tools("anything") == []


class TestDiscoverLocalConfigs:
    """discover_local_configs reads MCP server defs from JSON files."""

    def test_reads_claude_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".claude.json"
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "my-server": {
                            "command": "python",
                            "args": ["-m", "my_mcp"],
                            "env": {"KEY": "val"},
                        }
                    }
                }
            )
        )
        # Monkey-patch Path.home to return tmp_path
        import orqest.mcp.client as client_mod

        original = Path.home
        Path.home = staticmethod(lambda: tmp_path)  # type: ignore[assignment]
        try:
            configs = MCPServerManager.discover_local_configs()
        finally:
            Path.home = original  # type: ignore[assignment]

        assert len(configs) == 1
        assert configs[0].name == "my-server"
        assert configs[0].command == "python"
        assert configs[0].args == ["-m", "my_mcp"]
        assert configs[0].env == {"KEY": "val"}

    def test_skips_missing_files(self, tmp_path: Path) -> None:
        import orqest.mcp.client as client_mod

        original = Path.home
        Path.home = staticmethod(lambda: tmp_path)  # type: ignore[assignment]
        try:
            configs = MCPServerManager.discover_local_configs()
        finally:
            Path.home = original  # type: ignore[assignment]

        assert configs == []

    def test_handles_corrupt_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".claude.json"
        config_file.write_text("not valid json{{{")

        import orqest.mcp.client as client_mod

        original = Path.home
        Path.home = staticmethod(lambda: tmp_path)  # type: ignore[assignment]
        try:
            configs = MCPServerManager.discover_local_configs()
        finally:
            Path.home = original  # type: ignore[assignment]

        assert configs == []

    def test_deduplicates_across_files(self, tmp_path: Path) -> None:
        for name in [".claude.json", ".claude/claude.json"]:
            p = tmp_path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "shared": {"command": "node", "args": []}
                        }
                    }
                )
            )

        import orqest.mcp.client as client_mod

        original = Path.home
        Path.home = staticmethod(lambda: tmp_path)  # type: ignore[assignment]
        try:
            configs = MCPServerManager.discover_local_configs()
        finally:
            Path.home = original  # type: ignore[assignment]

        assert len(configs) == 1


class TestMCPConnectionTransport:
    """MCPConnection.connect() routes the transport by config.transport."""

    def test_stdio_transport_builds_a_context_manager(self) -> None:
        conn = MCPConnection(
            MCPServerConfig(name="s", command="python", args=["-m", "x"])
        )
        ctx = conn._open_transport()
        assert hasattr(ctx, "__aenter__")

    def test_sse_transport_builds_a_context_manager(self) -> None:
        conn = MCPConnection(
            MCPServerConfig(
                name="s",
                command="",
                transport="sse",
                url="http://localhost:3000/sse",
            )
        )
        ctx = conn._open_transport()
        assert hasattr(ctx, "__aenter__")

    def test_sse_transport_without_url_raises(self) -> None:
        conn = MCPConnection(
            MCPServerConfig(name="s", command="", transport="sse")
        )
        with pytest.raises(ValueError, match="no url"):
            conn._open_transport()

    def test_unknown_transport_raises(self) -> None:
        conn = MCPConnection(
            MCPServerConfig(name="s", command="x", transport="grpc")
        )
        with pytest.raises(ValueError, match="unknown transport"):
            conn._open_transport()
