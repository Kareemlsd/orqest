"""Tests for token-aware context management."""

import copy

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.context_manager import ContextManager
from orqest.utils.token_counter import (
    CHARS_PER_TOKEN,
    MESSAGE_OVERHEAD_TOKENS,
    estimate_text_tokens,
    estimate_tokens,
)


# --- Helpers ---


def _req(text: str = "hello") -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(text)])


def _resp(text: str = "reply") -> ModelResponse:
    return ModelResponse(parts=[TextPart(text)])


def _tool_call_resp(
    tool_name: str = "my_tool", tool_call_id: str = "tc1"
) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(tool_name=tool_name, args="", tool_call_id=tool_call_id)]
    )


def _tool_return_req(
    content: str = "result", tool_name: str = "my_tool", tool_call_id: str = "tc1"
) -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=tool_name, content=content, tool_call_id=tool_call_id
            )
        ]
    )


def _make_messages(count: int, text: str = "hello") -> list[ModelMessage]:
    """Create alternating request/response pairs."""
    msgs: list[ModelMessage] = []
    for i in range(count):
        if i % 2 == 0:
            msgs.append(_req(text))
        else:
            msgs.append(_resp(text))
    return msgs


def _make_tool_turn(
    tool_name: str = "my_tool",
    result_content: str = "result",
    tool_call_id: str = "tc1",
) -> list[ModelMessage]:
    """Create a tool call response + tool return request pair."""
    return [
        _tool_call_resp(tool_name=tool_name, tool_call_id=tool_call_id),
        _tool_return_req(
            content=result_content,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        ),
    ]


class SimpleOutput(BaseModel):
    text: str


class ConcreteAgent(BaseAgent["GlobalState", SimpleOutput]):
    async def _run_implementation(self, state, **kwargs):
        result = await self.call_model("test", state)
        return result.output


# --- Token estimation tests ---


class TestEstimateTokens:
    def test_empty_list(self):
        assert estimate_tokens([]) == 0

    def test_single_text_message(self):
        msgs = [_req("hello world")]
        tokens = estimate_tokens(msgs)
        # overhead (4) + len("hello world")/3.5 + 1 = 4 + 3 + 1 = 8
        expected = MESSAGE_OVERHEAD_TOKENS + int(len("hello world") / CHARS_PER_TOKEN) + 1
        assert tokens == expected

    def test_multiple_messages(self):
        msgs = [_req("abc"), _resp("def")]
        tokens = estimate_tokens(msgs)
        # Each: overhead + len/3.5 + 1
        expected = 2 * (MESSAGE_OVERHEAD_TOKENS + int(3 / CHARS_PER_TOKEN) + 1)
        assert tokens == expected

    def test_with_tool_results(self):
        content = "x" * 1000
        msgs = [_tool_return_req(content=content)]
        tokens = estimate_tokens(msgs)
        # overhead + len(content)/3.5 + 1
        expected = MESSAGE_OVERHEAD_TOKENS + int(1000 / CHARS_PER_TOKEN) + 1
        assert tokens == expected

    def test_tool_call_with_args(self):
        """ToolCallPart args are included in token estimate."""
        resp = ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="my_tool",
                    args='{"key": "value"}',
                    tool_call_id="tc1",
                )
            ]
        )
        msgs: list[ModelMessage] = [resp]
        tokens = estimate_tokens(msgs)
        # args content contributes to token count
        assert tokens > MESSAGE_OVERHEAD_TOKENS


class TestEstimateTextTokens:
    def test_empty_string(self):
        assert estimate_text_tokens("") == 1  # int(0/3.5) + 1

    def test_short_text(self):
        result = estimate_text_tokens("hello")
        expected = int(len("hello") / CHARS_PER_TOKEN) + 1
        assert result == expected

    def test_long_text(self):
        text = "x" * 10000
        result = estimate_text_tokens(text)
        expected = int(10000 / CHARS_PER_TOKEN) + 1
        assert result == expected


# --- ContextManager compact tests ---


class TestCompactNoop:
    """Messages below thresholds pass through unchanged."""

    def test_below_threshold(self):
        cm = ContextManager(token_budget=128_000, reserve=20_000)
        # effective_budget = 108_000; summarize at 60% = 64_800 tokens
        # Small messages are way below that
        msgs = _make_messages(10, text="short")
        result = cm.compact(msgs)
        assert result == msgs

    def test_empty_messages(self):
        cm = ContextManager()
        result = cm.compact([])
        assert result == []

    def test_returns_new_list(self):
        cm = ContextManager()
        msgs = _make_messages(4)
        result = cm.compact(msgs)
        assert result is not msgs


class TestCompactSummarize:
    """Summarization at 60% threshold."""

    def test_summarizes_at_60_percent(self):
        # effective_budget = 108_000; 60% = 64_800 tokens
        # Need messages totaling > 64_800 tokens but < 91_800 (85%)
        # At 3.5 chars/token, need ~227_000 chars of content
        cm = ContextManager(
            token_budget=128_000,
            reserve=20_000,
            min_recent_turns=2,
        )
        # Create initial user message
        msgs: list[ModelMessage] = [_req("initial context")]
        # Add tool turns with large content to push past 60%
        for i in range(10):
            msgs.extend(
                _make_tool_turn(
                    tool_name=f"tool_{i}",
                    result_content="x" * 25_000,
                    tool_call_id=f"tc_{i}",
                )
            )
        # Add recent messages
        msgs.append(_req("recent question"))
        msgs.append(_resp("recent answer"))

        tokens_before = estimate_tokens(msgs)
        effective = cm.effective_budget
        # Verify we're in the summarize range (60-85%)
        assert tokens_before > effective * 0.60
        assert tokens_before < effective * 0.85

        result = cm.compact(msgs)
        tokens_after = estimate_tokens(result)

        # Should be smaller
        assert tokens_after < tokens_before
        # First message preserved
        assert result[0].parts[0].content == "initial context"

    def test_preserves_recent_turns(self):
        cm = ContextManager(
            token_budget=128_000,
            reserve=20_000,
            min_recent_turns=3,
        )
        msgs: list[ModelMessage] = [_req("initial")]
        for i in range(10):
            msgs.extend(
                _make_tool_turn(
                    tool_name=f"tool_{i}",
                    result_content="x" * 25_000,
                    tool_call_id=f"tc_{i}",
                )
            )
        # Recent turns
        msgs.append(_req("recent1"))
        msgs.append(_resp("recent2"))
        msgs.append(_req("recent3"))

        tokens_before = estimate_tokens(msgs)
        if tokens_before <= cm.effective_budget * 0.60:
            pytest.skip("Messages don't exceed summarize threshold")

        result = cm.compact(msgs)

        # Last 3 messages should be preserved verbatim
        assert result[-1].parts[0].content == "recent3"
        assert result[-2].parts[0].content == "recent2"
        assert result[-3].parts[0].content == "recent1"

    def test_preserves_first_message(self):
        cm = ContextManager(
            token_budget=128_000,
            reserve=20_000,
            min_recent_turns=2,
        )
        msgs: list[ModelMessage] = [_req("very important initial context")]
        for i in range(10):
            msgs.extend(
                _make_tool_turn(
                    tool_name=f"tool_{i}",
                    result_content="x" * 25_000,
                    tool_call_id=f"tc_{i}",
                )
            )
        msgs.append(_req("recent"))
        msgs.append(_resp("answer"))

        result = cm.compact(msgs)
        assert result[0].parts[0].content == "very important initial context"

    def test_summarized_tool_call_format(self):
        """Summarized turns contain tool name and result status."""
        cm = ContextManager(
            token_budget=128_000,
            reserve=20_000,
            min_recent_turns=2,
        )
        msgs: list[ModelMessage] = [_req("initial")]
        for i in range(10):
            msgs.extend(
                _make_tool_turn(
                    tool_name=f"generate_mesh_{i}",
                    result_content="x" * 25_000,
                    tool_call_id=f"tc_{i}",
                )
            )
        msgs.append(_req("recent"))
        msgs.append(_resp("answer"))

        tokens_before = estimate_tokens(msgs)
        if tokens_before <= cm.effective_budget * 0.60:
            pytest.skip("Messages don't exceed summarize threshold")

        result = cm.compact(msgs)

        # Find summary messages (between first and recent)
        summary_texts = []
        for msg in result[1:-2]:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart) and isinstance(
                        part.content, str
                    ):
                        if "Called" in part.content or "[Context summary" in part.content:
                            summary_texts.append(part.content)

        # Should have summaries with tool names
        assert len(summary_texts) > 0
        combined = " ".join(summary_texts)
        assert "generate_mesh" in combined


class TestCompactTruncate:
    """Emergency truncation at 85% threshold."""

    def test_truncates_at_85_percent(self):
        cm = ContextManager(
            token_budget=128_000,
            reserve=20_000,
            min_recent_turns=3,
            min_recent_tokens=5_000,
        )
        # Push way past 85% threshold
        msgs: list[ModelMessage] = [_req("initial")]
        for i in range(20):
            msgs.extend(
                _make_tool_turn(
                    tool_name=f"tool_{i}",
                    result_content="x" * 30_000,
                    tool_call_id=f"tc_{i}",
                )
            )
        msgs.append(_req("recent question"))
        msgs.append(_resp("recent answer"))
        msgs.append(_req("latest"))

        tokens_before = estimate_tokens(msgs)
        assert tokens_before > cm.effective_budget * 0.85

        result = cm.compact(msgs)
        tokens_after = estimate_tokens(result)

        # Should be significantly smaller
        assert tokens_after < tokens_before
        # First message preserved
        assert result[0].parts[0].content == "initial"

    def test_emergency_preserves_min_tokens(self):
        cm = ContextManager(
            token_budget=128_000,
            reserve=20_000,
            min_recent_turns=2,
            min_recent_tokens=5_000,
        )
        msgs: list[ModelMessage] = [_req("initial")]
        for i in range(20):
            msgs.extend(
                _make_tool_turn(
                    tool_name=f"tool_{i}",
                    result_content="x" * 30_000,
                    tool_call_id=f"tc_{i}",
                )
            )
        msgs.append(_req("recent"))
        msgs.append(_resp("answer"))

        result = cm.compact(msgs)

        # Should preserve at least min_recent_tokens worth of recent messages
        # (excluding first message)
        recent_tokens = estimate_tokens(result[1:])
        assert recent_tokens >= cm.min_recent_tokens


class TestCompactImmutability:
    def test_never_mutates_input(self):
        cm = ContextManager(
            token_budget=128_000,
            reserve=20_000,
            min_recent_turns=2,
        )
        msgs: list[ModelMessage] = [_req("initial")]
        for i in range(10):
            msgs.extend(
                _make_tool_turn(
                    tool_name=f"tool_{i}",
                    result_content="x" * 25_000,
                    tool_call_id=f"tc_{i}",
                )
            )
        msgs.append(_req("recent"))
        msgs.append(_resp("answer"))

        original = copy.deepcopy(msgs)
        cm.compact(msgs)

        # Original list unchanged
        assert len(msgs) == len(original)
        for i, (msg, orig) in enumerate(zip(msgs, original)):
            assert type(msg) == type(orig)


# --- BaseAgent integration ---


class TestBaseAgentIntegration:
    def test_context_manager_wired_in_base_agent(self, test_model):
        cm = ContextManager()
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            context_manager=cm,
        )
        # context_manager.compact should be prepended as first processor
        first_proc = agent._history_processors[0]
        assert hasattr(first_proc, "__self__") and first_proc.__self__ is cm
        assert first_proc.__func__ is ContextManager.compact

    def test_context_manager_composable_with_budget(self, test_model):
        """context_manager works alongside budget_tool_results."""
        cm = ContextManager()
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            context_manager=cm,
            result_budget=20_000,
        )
        # Should have: context_manager.compact, budget_tool_results, keep_recent_messages = 3
        assert len(agent._history_processors) == 3
        # context_manager is first
        first_proc = agent._history_processors[0]
        assert hasattr(first_proc, "__self__") and first_proc.__self__ is cm

    def test_no_context_manager_default(self, test_model):
        """Without context_manager, default processors are unchanged."""
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        # Default: budget_tool_results + keep_recent_messages = 2
        assert len(agent._history_processors) == 2

    def test_context_manager_none_explicit(self, test_model):
        """Explicitly passing None is same as default."""
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            context_manager=None,
        )
        assert len(agent._history_processors) == 2
