"""Tests for budget_tool_results() history processor."""

import copy

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolReturnPart,
    UserPromptPart,
    TextPart,
    ToolCallPart,
)

from orqest.agents.base_agent import BaseAgent, budget_tool_results


# --- Helpers ---


def _req(text: str = "hello") -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(text)])


def _resp(text: str = "reply") -> ModelResponse:
    return ModelResponse(parts=[TextPart(text)])


def _tool_return_req(
    content: str = "result", tool_name: str = "my_tool", tool_call_id: str = "tc1"
) -> ModelRequest:
    return ModelRequest(
        parts=[ToolReturnPart(tool_name=tool_name, content=content, tool_call_id=tool_call_id)]
    )


def _tool_call_resp(tool_name: str = "my_tool", tool_call_id: str = "tc1") -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(tool_name=tool_name, args="", tool_call_id=tool_call_id)]
    )


class SimpleOutput(BaseModel):
    text: str


class ConcreteAgent(BaseAgent["GlobalState", SimpleOutput]):
    async def _run_implementation(self, state, **kwargs):
        result = await self.call_model("test", state)
        return result.output


# --- budget_tool_results() tests ---


class TestBudgetToolResultsNoop:
    """Cases where no truncation should occur."""

    def test_empty_list(self):
        assert budget_tool_results([]) == []

    def test_no_tool_returns(self):
        msgs = [_req("hi"), _resp("hello")]
        result = budget_tool_results(msgs, max_result_chars=100)
        assert len(result) == 2

    def test_under_limit(self):
        """Tool return content under the limit passes through unchanged."""
        small_content = "x" * 100
        msgs = [_req(), _tool_call_resp(), _tool_return_req(content=small_content), _resp()]
        result = budget_tool_results(msgs, max_result_chars=200)
        # Find the tool return part
        tool_req = result[2]
        assert isinstance(tool_req, ModelRequest)
        tool_part = tool_req.parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        assert str(tool_part.content) == small_content

    def test_exactly_at_limit(self):
        """Content exactly at max_result_chars is not truncated."""
        content = "x" * 500
        msgs = [_tool_return_req(content=content)]
        result = budget_tool_results(msgs, max_result_chars=500)
        tool_part = result[0].parts[0]
        assert str(tool_part.content) == content


class TestBudgetToolResultsTruncation:
    """Cases where truncation should occur."""

    def test_truncates_oversized(self):
        """Content exceeding max_result_chars gets truncated with preview."""
        big_content = "A" * 30_000
        msgs = [_tool_return_req(content=big_content)]
        result = budget_tool_results(msgs, max_result_chars=20_000, preview_chars=2_000)

        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        truncated = str(tool_part.content)

        # Starts with preview
        assert truncated.startswith("A" * 2_000)
        # Contains truncation notice
        assert "[TRUNCATED" in truncated
        assert "30000 chars total" in truncated
        # Shorter than original
        assert len(truncated) < 30_000

    def test_preserves_small_results_alongside_large(self):
        """Only oversized results are truncated; small ones are untouched."""
        small = _tool_return_req(content="small", tool_call_id="tc1")
        big = _tool_return_req(content="B" * 25_000, tool_call_id="tc2")
        msgs = [small, big]
        result = budget_tool_results(msgs, max_result_chars=20_000)

        # First tool return (small) unchanged
        assert str(result[0].parts[0].content) == "small"
        # Second tool return (big) truncated
        assert "[TRUNCATED" in str(result[1].parts[0].content)

    def test_custom_limits(self):
        """Custom max_result_chars and preview_chars work."""
        content = "X" * 500
        msgs = [_tool_return_req(content=content)]
        result = budget_tool_results(msgs, max_result_chars=100, preview_chars=50)

        truncated = str(result[0].parts[0].content)
        assert truncated.startswith("X" * 50)
        assert "[TRUNCATED" in truncated
        assert "500 chars total" in truncated

    def test_non_str_content(self):
        """Non-str content is converted via str() for length check."""
        # Use a dict as content — str(dict) produces a string
        big_dict = {"data": "Y" * 25_000}
        msgs = [ModelRequest(
            parts=[ToolReturnPart(tool_name="t", content=big_dict, tool_call_id="tc1")]
        )]
        result = budget_tool_results(msgs, max_result_chars=100, preview_chars=50)
        truncated = str(result[0].parts[0].content)
        assert "[TRUNCATED" in truncated

    def test_preserves_tool_metadata(self):
        """tool_name and tool_call_id are preserved after truncation."""
        msgs = [_tool_return_req(
            content="Z" * 30_000,
            tool_name="special_tool",
            tool_call_id="special_id",
        )]
        result = budget_tool_results(msgs, max_result_chars=100)
        part = result[0].parts[0]
        assert isinstance(part, ToolReturnPart)
        assert part.tool_name == "special_tool"
        assert part.tool_call_id == "special_id"


class TestBudgetToolResultsStructure:
    """Structural integrity tests."""

    def test_returns_new_list(self):
        msgs = [_req(), _resp()]
        result = budget_tool_results(msgs)
        assert result is not msgs

    def test_never_mutates_input(self):
        big_content = "M" * 30_000
        msgs = [_tool_return_req(content=big_content)]
        original_content = str(msgs[0].parts[0].content)
        budget_tool_results(msgs, max_result_chars=100)
        # Original unchanged
        assert str(msgs[0].parts[0].content) == original_content

    def test_preserves_message_ordering(self):
        """ModelRequest/ModelResponse ordering is preserved."""
        msgs = [
            _req("start"),
            _resp("ack"),
            _tool_call_resp(),
            _tool_return_req(content="R" * 30_000),
            _resp("final"),
        ]
        result = budget_tool_results(msgs, max_result_chars=100)
        assert len(result) == 5
        assert isinstance(result[0], ModelRequest)
        assert isinstance(result[1], ModelResponse)
        assert isinstance(result[2], ModelResponse)
        assert isinstance(result[3], ModelRequest)
        assert isinstance(result[4], ModelResponse)

    def test_mixed_parts_in_single_request(self):
        """A ModelRequest with both UserPromptPart and ToolReturnPart."""
        big_content = "W" * 30_000
        req = ModelRequest(parts=[
            UserPromptPart("user text"),
            ToolReturnPart(tool_name="t", content=big_content, tool_call_id="tc1"),
        ])
        msgs = [req]
        result = budget_tool_results(msgs, max_result_chars=100, preview_chars=50)

        # UserPromptPart unchanged
        assert isinstance(result[0].parts[0], UserPromptPart)
        assert result[0].parts[0].content == "user text"
        # ToolReturnPart truncated
        assert "[TRUNCATED" in str(result[0].parts[1].content)


class TestBudgetToolResultsDisabled:
    """When result_budget is None, budget processor is not in the chain."""

    def test_disabled_when_none(self, test_model):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            result_budget=None,
        )
        # keep_recent_messages + _repair_orphan_tool_returns appended = 2
        assert len(agent._history_processors) == 2


class TestBaseAgentResultBudget:
    """BaseAgent integration with result_budget parameter."""

    def test_default_includes_budget_processor(self, test_model):
        """Default BaseAgent has budget_tool_results in processor chain."""
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        # budget_tool_results + keep_recent_messages + _repair_orphan_tool_returns = 3
        assert len(agent._history_processors) == 3

    def test_custom_result_budget(self, test_model):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            result_budget=50_000,
        )
        assert len(agent._history_processors) == 3

    def test_custom_history_processors_with_budget(self, test_model):
        """Custom history_processors still get budget prepended."""
        custom = lambda msgs: msgs
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            history_processors=[custom],
            result_budget=10_000,
        )
        # budget + custom + repair = 3
        assert len(agent._history_processors) == 3

    def test_budget_none_with_custom_processors(self, test_model):
        """result_budget=None does not prepend budget processor."""
        custom = lambda msgs: msgs
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            history_processors=[custom],
            result_budget=None,
        )
        # custom + repair = 2
        assert len(agent._history_processors) == 2
        assert agent._history_processors[0] is custom
