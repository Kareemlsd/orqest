import json

import pytest
from pydantic import BaseModel, Field
from pydantic_ai import Tool
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.agents.tool_wrapper import as_tool


class AnalysisOutput(BaseModel):
    result: str = Field(description="The analysis result")


class AnalysisAgent(BaseAgent[GlobalState, AnalysisOutput]):
    async def _run_implementation(self, state: GlobalState, **kwargs) -> AnalysisOutput:
        user_msg = state.get_latest_message("user") or ""
        result = await self.agent.run(user_msg)
        return result.output


@pytest.fixture
def analysis_agent(test_model):
    return AnalysisAgent(
        agent_name="analysis_agent",
        system_prompt="You analyze text.",
        output_type=AnalysisOutput,
        model=test_model,
    )


class TestAsTool:
    def test_returns_tool(self, analysis_agent):
        tool = as_tool(analysis_agent, description="Analyze text")
        assert isinstance(tool, Tool)

    def test_tool_name_defaults_to_agent_name(self, analysis_agent):
        tool = as_tool(analysis_agent, description="Analyze text")
        assert tool.name == "analysis_agent"

    def test_tool_name_override(self, analysis_agent):
        tool = as_tool(analysis_agent, name="custom_name", description="Analyze text")
        assert tool.name == "custom_name"

    def test_tool_description(self, analysis_agent):
        tool = as_tool(analysis_agent, description="Analyze text for sentiment")
        assert tool.description == "Analyze text for sentiment"


class TestAsToolExecution:
    @pytest.mark.asyncio
    async def test_tool_runs_agent_and_returns_json(self, analysis_agent):
        tool = as_tool(analysis_agent, description="Analyze text")

        # Call the underlying wrapped function directly
        inner_fn = tool.function
        result = await inner_fn("test input")
        parsed = json.loads(result)
        assert "result" in parsed

    @pytest.mark.asyncio
    async def test_tool_is_stateless(self, analysis_agent):
        tool = as_tool(analysis_agent, description="Analyze text")

        inner_fn = tool.function
        # Two calls should be independent — each gets a fresh state
        result1 = await inner_fn("first call")
        result2 = await inner_fn("second call")

        # Both should succeed independently
        assert json.loads(result1)["result"]
        assert json.loads(result2)["result"]

    @pytest.mark.asyncio
    async def test_end_to_end_orchestrator(self, test_model):
        """An orchestrator agent uses a wrapped agent as a tool."""
        from pydantic_ai import Agent

        # Create the inner agent
        inner = AnalysisAgent(
            agent_name="inner_analyst",
            system_prompt="You analyze text.",
            output_type=AnalysisOutput,
            model=test_model,
        )

        # Wrap as tool
        tool = as_tool(inner, description="Analyze text for the user")

        # Create orchestrator with this tool
        orchestrator = Agent(
            model=test_model,
            tools=[tool],
        )

        # Run the orchestrator — TestModel will call all available tools
        result = await orchestrator.run("Please analyze this text")
        assert result.output is not None
