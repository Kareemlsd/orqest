import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    UserPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from orqest.agents.base_agent import BaseAgent, keep_recent_messages


# --- Helpers ---

def _req(text: str = "hello") -> ModelRequest:
    """Create a simple ModelRequest with a user prompt."""
    return ModelRequest(parts=[UserPromptPart(text)])


def _resp(text: str = "reply") -> ModelResponse:
    """Create a simple ModelResponse with text."""
    return ModelResponse(parts=[TextPart(text)])


def _tool_call_resp() -> ModelResponse:
    """Create a ModelResponse with a tool call."""
    return ModelResponse(parts=[ToolCallPart(tool_name="my_tool", args="", tool_call_id="tc1")])


def _tool_return_req() -> ModelRequest:
    """Create a ModelRequest with a tool return."""
    return ModelRequest(parts=[ToolReturnPart(tool_name="my_tool", content="result", tool_call_id="tc1")])


class SimpleOutput(BaseModel):
    text: str


class ConcreteAgent(BaseAgent["GlobalState", SimpleOutput]):
    """Minimal concrete agent for testing."""

    async def _run_implementation(self, state, **kwargs):
        result = await self.agent.run("test")
        return result.output


class FailingAgent(BaseAgent["GlobalState", SimpleOutput]):
    """Agent that always raises."""

    async def _run_implementation(self, state, **kwargs):
        raise RuntimeError("intentional failure")


# --- keep_recent_messages tests ---

class TestKeepRecentMessages:
    def test_empty_list(self):
        assert keep_recent_messages([]) == []

    def test_shorter_than_max(self):
        msgs = [_req(), _resp()]
        result = keep_recent_messages(msgs, max_messages=10)
        assert len(result) == 2

    def test_returns_new_list(self):
        msgs = [_req(), _resp()]
        result = keep_recent_messages(msgs, max_messages=10)
        assert result is not msgs

    def test_does_not_mutate_input(self):
        msgs = [_req(), _resp(), _req("two"), _resp("two")]
        original_len = len(msgs)
        keep_recent_messages(msgs, max_messages=2)
        assert len(msgs) == original_len

    def test_truncates_to_max(self):
        msgs = [_req("first"), _resp("1"), _req("2"), _resp("2"), _req("3"), _resp("3")]
        result = keep_recent_messages(msgs, max_messages=2)
        # Last 2 are [req("3"), resp("3")]. req("3") at boundary triggers repair:
        # preceding resp("2") is included. Total: first + resp("2") + req("3") + resp("3")
        assert len(result) == 4
        assert result[0] is msgs[0]

    def test_preserves_first_message(self):
        msgs = [_req("first"), _resp("1"), _req("2"), _resp("2")]
        result = keep_recent_messages(msgs, max_messages=1)
        assert result[0] is msgs[0]

    def test_tool_call_pair_preserved(self):
        # [req, resp, tool_call_resp, tool_return_req, resp]
        msgs = [_req("init"), _resp("1"), _tool_call_resp(), _tool_return_req(), _resp("final")]
        # max_messages=2 would take [tool_return_req, resp] — splitting the pair
        # So the tool_call_resp should be included
        result = keep_recent_messages(msgs, max_messages=2)
        # Should include: first msg + tool_call_resp + tool_return_req + final resp
        assert any(isinstance(m, ModelResponse) for m in result)
        assert any(isinstance(m, ModelRequest) for m in result)
        # The tool call response should be preserved (was at index 2)
        assert msgs[2] in result

    def test_max_messages_zero(self):
        msgs = [_req(), _resp()]
        result = keep_recent_messages(msgs, max_messages=0)
        assert len(result) == 2


# --- BaseAgent construction tests ---

class TestBaseAgentConstruction:
    def test_with_model_instance(self, test_model):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="you are helpful",
            output_type=SimpleOutput,
            model=test_model,
        )
        assert agent.model is test_model

    def test_with_string_model_requires_api_key(self):
        with pytest.raises(ValueError, match="api_key is required"):
            ConcreteAgent(
                agent_name="test",
                system_prompt="you are helpful",
                output_type=SimpleOutput,
                model="openai:gpt-4o",
            )

    def test_with_string_model_and_api_key(self):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="you are helpful",
            output_type=SimpleOutput,
            model="openai:gpt-4o",
            api_key="test-key",
        )
        assert agent.model is not None

    def test_invalid_model_type_raises(self):
        with pytest.raises(TypeError, match="Model instance"):
            ConcreteAgent(
                agent_name="test",
                system_prompt="you are helpful",
                output_type=SimpleOutput,
                model=12345,
            )

    def test_agent_property_creates_agent(self, test_model):
        base = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        agent = base.agent
        assert agent is not None
        # Second access returns the same instance
        assert base.agent is agent

    def test_custom_history_processors(self, test_model):
        custom = lambda msgs: msgs[-1:]
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            history_processors=[custom],
        )
        assert agent._history_processors == [custom]

    def test_default_history_processor(self, test_model):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            truncated_history=50,
        )
        assert len(agent._history_processors) == 1


# --- BaseAgent.run() tests ---

class TestBaseAgentRun:
    @pytest.mark.asyncio
    async def test_run_propagates_exceptions(self, test_model):
        agent = FailingAgent(
            agent_name="fail",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        from orqest.agents.state import GlobalState
        state = GlobalState()
        with pytest.raises(RuntimeError, match="intentional failure"):
            await agent.run(state)

    @pytest.mark.asyncio
    async def test_run_returns_output(self, test_model):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        from orqest.agents.state import GlobalState
        state = GlobalState()
        result = await agent.run(state)
        assert isinstance(result, SimpleOutput)
