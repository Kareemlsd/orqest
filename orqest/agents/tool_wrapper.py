"""Wrap a BaseAgent as a pydantic-ai Tool.

This enables the agent-as-tool composition pattern: an orchestrating agent can
call specialized agents on demand, without those agents needing conversation
history. Each tool invocation is stateless — a fresh state is created, the query
is passed in, and the structured output is returned as JSON.
"""
from __future__ import annotations

from pydantic_ai import Tool

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState


def as_tool(
    agent: BaseAgent,
    *,
    name: str | None = None,
    description: str,
) -> Tool:
    """Wrap a BaseAgent as a pydantic-ai Tool.

    The orchestrating agent's LLM sees a tool with a single `query` parameter.
    When invoked, a fresh GlobalState is created, the query is added as a user
    message, and the wrapped agent runs statelessly. The output is returned as
    a JSON string.

    Args:
        agent: The BaseAgent instance to wrap.
        name: Tool name visible to the LLM. Defaults to agent.agent_name.
        description: Tool description visible to the LLM. Should clearly explain
            what the agent does and when to use it.
    """
    tool_name = name or agent.agent_name

    async def _run(query: str) -> str:
        """Execute the wrapped agent with a fresh state.

        Args:
            query: The input to send to the agent.
        """
        state = GlobalState()
        state.add_message("user", query)
        output = await agent.run(state)
        return output.model_dump_json()

    _run.__name__ = tool_name
    _run.__qualname__ = tool_name

    return Tool(_run, name=tool_name, description=description)
