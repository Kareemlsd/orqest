"""Tests for MCP configuration dataclasses."""

from __future__ import annotations

import dataclasses

import pytest

from orqest.mcp.config import MCPConfig, MCPServerConfig


class TestMCPServerConfig:
    """MCPServerConfig is a frozen dataclass with sensible defaults."""

    def test_minimal(self) -> None:
        cfg = MCPServerConfig(name="test", command="python")
        assert cfg.name == "test"
        assert cfg.command == "python"
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.transport == "stdio"
        assert cfg.url is None

    def test_all_fields(self) -> None:
        cfg = MCPServerConfig(
            name="my-server",
            command="node",
            args=["server.js"],
            env={"API_KEY": "secret"},
            transport="sse",
            url="http://localhost:3000",
        )
        assert cfg.transport == "sse"
        assert cfg.url == "http://localhost:3000"
        assert cfg.env["API_KEY"] == "secret"

    def test_frozen(self) -> None:
        cfg = MCPServerConfig(name="x", command="y")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.name = "z"  # type: ignore[misc]


class TestMCPConfig:
    """MCPConfig is a frozen dataclass with auto_discover=True by default."""

    def test_defaults(self) -> None:
        cfg = MCPConfig()
        assert cfg.servers == []
        assert cfg.auto_discover is True
        assert cfg.connection_timeout == 30.0

    def test_custom_servers(self) -> None:
        s = MCPServerConfig(name="s1", command="python")
        cfg = MCPConfig(servers=[s], auto_discover=False)
        assert len(cfg.servers) == 1
        assert cfg.auto_discover is False

    def test_frozen(self) -> None:
        cfg = MCPConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.auto_discover = False  # type: ignore[misc]
