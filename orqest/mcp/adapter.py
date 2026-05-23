"""Bridge MCP tool definitions to pydantic-ai Tool instances."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic_ai import Tool


class MCPToolAdapter:
    """Convert MCP tool definitions into pydantic-ai Tool instances.

    MCP tools are described by name, description, and a JSON Schema for
    their parameters.  This adapter creates an async wrapper function that
    calls the MCP server and packages the result as a pydantic-ai ``Tool``.
    """

    @staticmethod
    def adapt(
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        call_fn: Any,
    ) -> Tool:
        """Create a pydantic-ai Tool from a single MCP tool definition.

        Args:
            tool_name: The MCP tool name.
            tool_description: Human-readable description shown to the LLM.
            input_schema: JSON Schema for the tool's input parameters.
            call_fn: Async callable ``(tool_name, arguments_dict) -> result``.

        Returns:
            A pydantic-ai ``Tool`` wrapping the MCP call.

        """

        async def _mcp_wrapper(**kwargs: Any) -> str:
            try:
                result = await call_fn(tool_name, kwargs)
                return _extract_text(result)
            except Exception as exc:
                logger.warning(
                    "MCP tool {name} failed: {err}",
                    name=tool_name,
                    err=exc,
                )
                return f"Error calling {tool_name}: {exc}"

        return Tool(
            _mcp_wrapper,
            name=tool_name,
            description=tool_description,
        )

    @staticmethod
    def adapt_many(
        tool_defs: list[dict[str, Any]],
        call_fn: Any,
    ) -> list[Tool]:
        """Convert a list of MCP tool definitions to pydantic-ai Tools.

        Each entry in *tool_defs* must have ``name`` and may have
        ``description`` and ``inputSchema`` keys (matching the MCP
        ``ListToolsResult`` shape).

        """
        adapted: list[Tool] = []
        for defn in tool_defs:
            name = defn.get("name", "")
            if not name:
                continue
            adapted.append(
                MCPToolAdapter.adapt(
                    tool_name=name,
                    tool_description=defn.get("description", ""),
                    input_schema=defn.get("inputSchema", {}),
                    call_fn=call_fn,
                )
            )
        return adapted


def _extract_text(result: Any) -> str:
    """Pull text from an MCP CallToolResult (content blocks)."""
    if hasattr(result, "content"):
        texts = []
        for block in result.content:
            if hasattr(block, "text"):
                texts.append(block.text)
        if texts:
            return "\n".join(texts)
    return str(result)
