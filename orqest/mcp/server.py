"""Expose Orqest as an MCP server for Claude Code and other clients."""

from __future__ import annotations

from typing import Any

from loguru import logger


def create_orqest_server(
    factory: Any = None,
    registry: Any = None,
    meta: Any = None,
    default_model: str = "openai:gpt-4o",
    api_key: str = "",
) -> Any:
    """Create a FastMCP server exposing Orqest capabilities.

    Tools exposed:

    - **create_agent** — define a new agent from a JSON spec
    - **run_agent** — execute a named agent with text input
    - **solve_goal** — use the MetaOrchestrator for complex goals
    - **list_agents** — enumerate available agents

    Args:
        factory: An ``AgentFactory`` instance (optional).
        registry: A ``ToolRegistry`` instance (optional).
        meta: A ``MetaOrchestrator`` instance (optional).
        default_model: Model string used when specs omit one.
        api_key: LLM API key for spawned agents.

    Returns:
        A ``FastMCP`` server instance ready to be run.

    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("orqest")
    _agents: dict[str, Any] = {}

    @mcp.tool()
    async def create_agent(
        name: str,
        system_prompt: str,
        output_schema: str,
        model: str = "",
    ) -> str:
        """Create a new Orqest agent from a specification.

        *output_schema* is a JSON string describing the output fields.
        """
        import json as _json

        from orqest.autonomy.spec import AgentSpec

        try:
            spec = AgentSpec(
                name=name,
                system_prompt=system_prompt,
                output_schema=_json.loads(output_schema),
                model=model or default_model,
            )
            if factory is None:
                return "No AgentFactory configured on the server."
            agent = factory.spawn(spec)
            _agents[name] = agent
            return f"Agent '{name}' created successfully."
        except Exception as exc:
            logger.warning("create_agent failed: {e}", e=exc)
            return f"Failed to create agent: {exc}"

    @mcp.tool()
    async def run_agent(name: str, input_text: str) -> str:
        """Run a previously created agent with text input."""
        from orqest.agents.state import GlobalState

        agent = _agents.get(name)
        if agent is None:
            return (
                f"Agent '{name}' not found. "
                f"Available: {list(_agents.keys())}"
            )
        state = GlobalState()
        state.add_message("user", input_text)
        try:
            result = await agent.run(state)
            if hasattr(result, "model_dump_json"):
                return result.model_dump_json(indent=2)
            return str(result)
        except Exception as exc:
            return f"Agent '{name}' failed: {exc}"

    @mcp.tool()
    async def solve_goal(goal: str) -> str:
        """Decompose and solve a complex goal via MetaOrchestrator."""
        if meta is None:
            return "No MetaOrchestrator configured on the server."
        try:
            result = await meta.solve(goal)
            return result.summary
        except Exception as exc:
            return f"MetaOrchestrator failed: {exc}"

    @mcp.tool()
    async def list_agents() -> str:
        """List all agents available on this server."""
        import json as _json

        info = [
            {"name": n, "type": type(a).__name__}
            for n, a in _agents.items()
        ]
        return _json.dumps(info, indent=2)

    return mcp
