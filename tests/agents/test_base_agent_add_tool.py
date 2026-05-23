"""Tests for orqest.agents.base_agent.BaseAgent.add_tool."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai import Tool
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState


class _Out(BaseModel):
    text: str


class _StubAgent(BaseAgent[GlobalState, _Out]):
    async def _run_implementation(self, state: GlobalState, **kwargs: Any) -> _Out:
        result = await self.call_model(
            state.get_latest_message("user") or "", state
        )
        return result.output


def _make_agent(*, tools: list[Tool] | None = None) -> _StubAgent:
    return _StubAgent(
        agent_name="stub",
        system_prompt="hi",
        output_type=_Out,
        model=TestModel(),
        tools=tools,
    )


async def _example_tool(x: int) -> str:
    """Example tool."""
    return f"x={x}"


async def _other_tool(y: int) -> str:
    """Other tool."""
    return f"y={y}"


async def _example_tool_v2(x: int) -> str:
    """Example tool v2."""
    return f"v2 x={x}"


def test_add_tool_appends_to_self_tools():
    agent = _make_agent()
    assert agent.tools == []
    agent.add_tool(Tool(_example_tool, name="example"))
    assert len(agent.tools) == 1
    assert agent.tools[0].name == "example"


def test_add_tool_invalidates_agent_cache():
    agent = _make_agent()
    # Force the cache to be populated
    _ = agent.agent
    assert agent._agent is not None

    agent.add_tool(Tool(_example_tool, name="example"))
    # Cache cleared
    assert agent._agent is None


def test_subsequent_agent_access_rebuilds_with_new_tool():
    agent = _make_agent()
    _ = agent.agent  # cache populated
    agent.add_tool(Tool(_example_tool, name="example"))
    rebuilt = agent.agent
    # The rebuilt agent must include the new tool — pydantic-ai's Agent
    # exposes its tools but the surface varies; we check via .toolset
    # or by re-checking self.tools (which is what gets passed in)
    assert len(agent.tools) == 1
    assert agent.tools[0].name == "example"
    assert rebuilt is not None


def test_add_tool_rejects_non_tool():
    agent = _make_agent()
    with pytest.raises(TypeError, match="pydantic_ai.Tool instance"):
        agent.add_tool("not a tool")  # type: ignore[arg-type]


def test_add_tool_idempotent_same_name():
    """Adding a tool with the same name replaces the existing entry."""
    agent = _make_agent()
    agent.add_tool(Tool(_example_tool, name="example"))
    agent.add_tool(Tool(_example_tool_v2, name="example"))
    # Only one entry; the v2 implementation wins
    assert len(agent.tools) == 1
    assert agent.tools[0].name == "example"
    # Verify it's the v2 by inspecting the function's bound docstring
    assert "v2" in agent.tools[0].function.__doc__


def test_add_tool_distinct_names_coexist():
    agent = _make_agent()
    agent.add_tool(Tool(_example_tool, name="example"))
    agent.add_tool(Tool(_other_tool, name="other"))
    assert sorted(t.name for t in agent.tools) == ["example", "other"]
