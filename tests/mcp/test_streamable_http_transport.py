"""Tests for the streamable-http transport branch in MCPConnection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from orqest.mcp.client import MCPConnection
from orqest.mcp.config import MCPServerConfig


def test_config_carries_headers_field():
    cfg = MCPServerConfig(
        name="test", command="", transport="streamable-http",
        url="http://localhost:8000/mcp",
        headers={"Authorization": "Bearer xyz", "X-Custom": "1"},
    )
    assert cfg.headers == {"Authorization": "Bearer xyz", "X-Custom": "1"}


def test_default_headers_empty():
    cfg = MCPServerConfig(name="test", command="python")
    assert cfg.headers == {}


def test_streamable_http_requires_url():
    cfg = MCPServerConfig(
        name="test", command="", transport="streamable-http", url=None
    )
    conn = MCPConnection(cfg)
    with pytest.raises(ValueError, match="streamable-http transport but has no url"):
        conn._open_transport()


def test_streamable_http_passes_headers_through():
    """Verify the streamablehttp_client is called with the configured headers."""
    cfg = MCPServerConfig(
        name="test",
        command="",
        transport="streamable-http",
        url="http://127.0.0.1:8000/mcp",
        headers={"Authorization": "Bearer abc"},
    )
    conn = MCPConnection(cfg)

    with patch("mcp.client.streamable_http.streamablehttp_client") as mock_client:
        mock_client.return_value = "context-manager"
        result = conn._open_transport()
        mock_client.assert_called_once_with(
            "http://127.0.0.1:8000/mcp",
            headers={"Authorization": "Bearer abc"},
        )
        assert result == "context-manager"


def test_streamable_http_no_headers_passes_none():
    """Empty headers dict should pass `headers=None` to keep the SDK happy."""
    cfg = MCPServerConfig(
        name="test", command="", transport="streamable-http",
        url="http://127.0.0.1:8000/mcp",
    )
    conn = MCPConnection(cfg)
    with patch("mcp.client.streamable_http.streamablehttp_client") as mock_client:
        conn._open_transport()
        mock_client.assert_called_once_with(
            "http://127.0.0.1:8000/mcp",
            headers=None,
        )


def test_unknown_transport_lists_streamable_http_in_error():
    cfg = MCPServerConfig(name="test", command="x", transport="ghost")
    conn = MCPConnection(cfg)
    with pytest.raises(ValueError, match="streamable-http"):
        conn._open_transport()


def test_existing_stdio_branch_still_works():
    cfg = MCPServerConfig(name="test", command="python", args=["-V"])
    conn = MCPConnection(cfg)
    with patch("mcp.client.stdio.stdio_client") as mock_client:
        conn._open_transport()
        # Just verify it routed to stdio_client without raising; arg shape
        # is upstream's concern
        assert mock_client.called


def test_existing_sse_branch_still_works():
    cfg = MCPServerConfig(
        name="test", command="", transport="sse",
        url="http://localhost:9000/sse",
    )
    conn = MCPConnection(cfg)
    with patch("mcp.client.sse.sse_client") as mock_client:
        conn._open_transport()
        mock_client.assert_called_once_with("http://localhost:9000/sse")
