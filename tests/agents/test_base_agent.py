from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai import ImageUrl, DocumentUrl, BinaryContent
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
        prompt = state.get_latest_message("user") or "test"
        result = await self.call_model(prompt, state)
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
        # budget_tool_results prepended + custom + _repair_orphan_tool_returns appended = 3
        assert len(agent._history_processors) == 3
        assert agent._history_processors[1] is custom

    def test_custom_history_processors_no_budget(self, test_model):
        custom = lambda msgs: msgs[-1:]
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            history_processors=[custom],
            result_budget=None,
        )
        # custom + _repair_orphan_tool_returns appended = 2
        assert len(agent._history_processors) == 2
        assert agent._history_processors[0] is custom

    def test_default_history_processor(self, test_model):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            truncated_history=50,
        )
        # budget_tool_results + keep_recent_messages + _repair_orphan_tool_returns = 3
        assert len(agent._history_processors) == 3


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
        state.add_message("user", "hello")
        result = await agent.run(state)
        assert isinstance(result, SimpleOutput)


# --- Multi-turn conversation tests ---

class TestCallModel:
    @pytest.mark.asyncio
    async def test_populates_message_history(self, test_model):
        """After one call_model(), state.message_history should be non-empty."""
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        from orqest.agents.state import GlobalState
        state = GlobalState()
        state.add_message("user", "hello")
        await agent.run(state)
        assert len(state.message_history) > 0

    @pytest.mark.asyncio
    async def test_accumulates_history(self, test_model):
        """Two consecutive calls should accumulate message history."""
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        from orqest.agents.state import GlobalState
        state = GlobalState()

        # First turn
        state.add_message("user", "first message")
        await agent.run(state)
        history_after_first = len(state.message_history)

        # Second turn
        state.add_message("user", "second message")
        await agent.run(state)
        history_after_second = len(state.message_history)

        assert history_after_second > history_after_first

    @pytest.mark.asyncio
    async def test_returns_agent_run_result(self, test_model):
        """call_model() should return a pydantic-ai AgentRunResult."""
        from pydantic_ai.run import AgentRunResult
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        state.add_message("user", "hello")
        result = await agent.call_model("hello", state)
        assert isinstance(result, AgentRunResult)

    @pytest.mark.asyncio
    async def test_history_contains_request_and_response(self, test_model):
        """After a call, history should contain both ModelRequest and ModelResponse."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        state.add_message("user", "hello")
        await agent.run(state)

        has_request = any(isinstance(m, ModelRequest) for m in state.message_history)
        has_response = any(isinstance(m, ModelResponse) for m in state.message_history)
        assert has_request
        assert has_response

    @pytest.mark.asyncio
    async def test_empty_history_on_first_call(self, test_model):
        """First call should work with empty message_history."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        assert state.message_history == []
        state.add_message("user", "hello")
        output = await agent.run(state)
        assert isinstance(output, SimpleOutput)


# --- Streaming tests ---

class TestStreaming:
    @pytest.mark.asyncio
    async def test_call_model_stream_yields_result(self, test_model):
        """call_model_stream() should yield a StreamedRunResult."""
        from pydantic_ai.result import StreamedRunResult
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        async with agent.call_model_stream("hello", state) as streamed:
            assert isinstance(streamed, StreamedRunResult)
            # Consume the stream so context manager exits cleanly
            await streamed.get_output()

    @pytest.mark.asyncio
    async def test_call_model_stream_updates_history(self, test_model):
        """state.message_history should be populated after stream is consumed."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        assert state.message_history == []
        async with agent.call_model_stream("hello", state) as streamed:
            await streamed.get_output()
        assert len(state.message_history) > 0

    @pytest.mark.asyncio
    async def test_call_model_stream_history_has_request_and_response(self, test_model):
        """After streaming, history should contain both request and response."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        async with agent.call_model_stream("hello", state) as streamed:
            await streamed.get_output()
        has_request = any(isinstance(m, ModelRequest) for m in state.message_history)
        has_response = any(isinstance(m, ModelResponse) for m in state.message_history)
        assert has_request
        assert has_response

    @pytest.mark.asyncio
    async def test_stream_output_yields_partial_models(self, test_model):
        """stream_output() should yield SimpleOutput instances."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        partials = []
        async for partial in agent.stream_output("hello", state):
            partials.append(partial)
        assert len(partials) > 0
        # Each yielded value should be a SimpleOutput (or partial of it)
        for p in partials:
            assert isinstance(p, SimpleOutput)

    @pytest.mark.asyncio
    async def test_stream_output_updates_history(self, test_model):
        """History should be updated after stream_output() generator is exhausted."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        assert state.message_history == []
        async for _ in agent.stream_output("hello", state):
            pass
        assert len(state.message_history) > 0

    @pytest.mark.asyncio
    async def test_stream_accumulates_history(self, test_model):
        """Second streaming call should see history from the first."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()

        # First streaming call
        async with agent.call_model_stream("first", state) as streamed:
            await streamed.get_output()
        history_after_first = len(state.message_history)

        # Second streaming call
        async with agent.call_model_stream("second", state) as streamed:
            await streamed.get_output()
        history_after_second = len(state.message_history)

        assert history_after_second > history_after_first

    @pytest.mark.asyncio
    async def test_stream_output_final_value_matches_get_output(self, test_model):
        """The last value from stream_output() should match get_output()."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        last_partial = None
        async for partial in agent.stream_output("hello", state):
            last_partial = partial
        assert last_partial is not None
        assert isinstance(last_partial, SimpleOutput)
        assert last_partial.text != ""

    @pytest.mark.asyncio
    async def test_stream_events_yields_events(self, test_model):
        """stream_events() should yield AgentStreamEvent instances."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        events = []
        async for event in agent.stream_events("hello", state):
            events.append(event)
        assert len(events) > 0
        # Should contain at least PartStartEvent and PartEndEvent
        event_kinds = {e.event_kind for e in events}
        assert "part_start" in event_kinds
        assert "part_end" in event_kinds

    @pytest.mark.asyncio
    async def test_stream_events_updates_history(self, test_model):
        """stream_events() should update state.message_history after exhaustion."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        assert state.message_history == []
        async for _ in agent.stream_events("hello", state):
            pass
        assert len(state.message_history) > 0

    @pytest.mark.asyncio
    async def test_stream_events_with_tools(self, test_model):
        """stream_events() should yield tool call and tool result events."""
        from pydantic_ai import Tool
        from orqest.agents.state import GlobalState

        def get_weather(city: str) -> str:
            """Get weather for a city."""
            return f"Sunny in {city}"

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            tools=[Tool(get_weather)],
        )
        state = GlobalState()
        events = []
        async for event in agent.stream_events("hello", state):
            events.append(event)

        event_kinds = {e.event_kind for e in events}
        # Should include tool call and result events
        assert "function_tool_call" in event_kinds
        assert "function_tool_result" in event_kinds


# --- Multi-modal prompt tests ---

class TestMultiModalPrompt:
    """Verify that multi-modal prompt types pass through to the underlying agent."""

    @pytest.mark.asyncio
    async def test_call_model_with_image_url(self, test_model):
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        result = await agent.call_model(
            ["Describe this image:", ImageUrl(url="https://example.com/img.png")],
            state,
        )
        assert isinstance(result.output, SimpleOutput)
        assert len(state.message_history) > 0

    @pytest.mark.asyncio
    async def test_call_model_with_document_url(self, test_model):
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        result = await agent.call_model(
            ["Summarize:", DocumentUrl(url="https://example.com/doc.pdf")],
            state,
        )
        assert isinstance(result.output, SimpleOutput)

    @pytest.mark.asyncio
    async def test_call_model_with_binary_content(self, test_model):
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        content = BinaryContent(data=b"\x89PNG fake image bytes", media_type="image/png")
        result = await agent.call_model(["What is this?", content], state)
        assert isinstance(result.output, SimpleOutput)

    @pytest.mark.asyncio
    async def test_call_model_with_mixed_content(self, test_model):
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        result = await agent.call_model(
            [
                "Compare these:",
                ImageUrl(url="https://example.com/a.png"),
                DocumentUrl(url="https://example.com/report.pdf"),
            ],
            state,
        )
        assert isinstance(result.output, SimpleOutput)

    @pytest.mark.asyncio
    async def test_call_model_stream_with_multimodal(self, test_model):
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        async with agent.call_model_stream(
            ["Describe:", ImageUrl(url="https://example.com/img.png")], state
        ) as streamed:
            await streamed.get_output()
        assert len(state.message_history) > 0

    @pytest.mark.asyncio
    async def test_stream_output_with_multimodal(self, test_model):
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        partials = []
        async for partial in agent.stream_output(
            ["Describe:", ImageUrl(url="https://example.com/img.png")], state
        ):
            partials.append(partial)
        assert len(partials) > 0

    @pytest.mark.asyncio
    async def test_stream_events_with_multimodal(self, test_model):
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        events = []
        async for event in agent.stream_events(
            ["Describe:", ImageUrl(url="https://example.com/img.png")], state
        ):
            events.append(event)
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_multimodal_history_persists_across_turns(self, test_model):
        """Multi-modal prompts should accumulate in message_history across turns."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()

        # First turn with image
        await agent.call_model(
            ["Describe:", ImageUrl(url="https://example.com/img.png")], state
        )
        history_after_first = len(state.message_history)

        # Second turn with document
        await agent.call_model(
            ["Summarize:", DocumentUrl(url="https://example.com/doc.pdf")], state
        )
        assert len(state.message_history) > history_after_first

    @pytest.mark.asyncio
    async def test_plain_string_still_works(self, test_model):
        """Ensure backwards compatibility — plain strings still work."""
        from orqest.agents.state import GlobalState

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        state = GlobalState()
        result = await agent.call_model("plain text prompt", state)
        assert isinstance(result.output, SimpleOutput)


class TestModelSettings:
    """model_settings kwarg threads into pydantic-ai Agent construction."""

    def test_default_is_none(self, test_model):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        assert agent.model_settings is None
        # Force lazy Agent construction; verify it didn't error.
        assert agent.agent is not None

    def test_custom_settings_stored_and_passed(self, test_model):
        from pydantic_ai.settings import ModelSettings

        settings = ModelSettings(temperature=0.0, seed=42)
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
            model_settings=settings,
        )
        assert agent.model_settings is settings
        # pydantic-ai's Agent stores settings on the instance; check it round-tripped
        assert agent.agent.model_settings == settings


class TestReasoning:
    """reasoning kwarg translates to provider-specific model_settings."""

    def test_default_is_none(self, test_model):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        assert agent.reasoning is None
        assert agent.model_settings is None

    def test_string_model_merges_provider_key(self):
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model="anthropic:claude-sonnet-4-6",
            api_key="k",
            reasoning="high",
        )
        assert agent.reasoning == "high"
        assert agent.model_settings["anthropic_thinking"]["type"] == "enabled"
        assert agent.agent.model_settings["anthropic_thinking"]["type"] == "enabled"

    def test_model_instance_uses_system_for_provider(self):
        from orqest.utils.llm_model import resolve_model

        model = resolve_model("google:gemini-2.5-pro", api_key="k")
        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=model,
            reasoning="low",
        )
        assert "google_thinking_config" in agent.model_settings

    def test_explicit_model_settings_win_on_conflict(self):
        from pydantic_ai.settings import ModelSettings

        agent = ConcreteAgent(
            agent_name="test",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model="openai:gpt-5.2",
            api_key="k",
            reasoning="medium",
            model_settings=ModelSettings(temperature=0.2),
        )
        # Both the reasoning key and the explicit setting survive the merge.
        assert agent.model_settings["openai_reasoning_effort"] == "medium"
        assert agent.model_settings["temperature"] == 0.2

    def test_unknown_provider_raises_at_construction(self, test_model):
        # TestModel.system == "test" — not a provider orqest can resolve.
        with pytest.raises(ValueError, match="not supported for provider"):
            ConcreteAgent(
                agent_name="test",
                system_prompt="prompt",
                output_type=SimpleOutput,
                model=test_model,
                reasoning="high",
            )


# --- output_type schema validation tests ---


class _OutputWithAnyField(BaseModel):
    """An output type that should be REJECTED at agent construction."""

    text: str
    payload: Any  # top-level Any — OpenAI rejects this at first inference


class _OutputWithMultipleAnyFields(BaseModel):
    foo: Any
    bar: Any
    name: str


class _OutputWithAnyInsideContainer(BaseModel):
    """Containers holding Any are FINE — they serialize to typed arrays/objects."""

    text: str
    extras: list[Any]
    metadata: dict[str, Any]


class TestOutputTypeSchemaValidation:
    """Reject top-level Any-typed fields in output_type at construction.

    These tests pin the BaseAgentSchemaError contract so the next OpenAI
    user doesn't lose 20 minutes diagnosing an opaque ModelHTTPError.
    """

    def test_rejects_top_level_any_field(self, test_model):
        from orqest.agents.base_agent import BaseAgentSchemaError

        with pytest.raises(BaseAgentSchemaError, match="'payload'"):
            ConcreteAgent(
                agent_name="test",
                system_prompt="prompt",
                output_type=_OutputWithAnyField,
                model=test_model,
            )

    def test_error_message_names_offending_field(self, test_model):
        from orqest.agents.base_agent import BaseAgentSchemaError

        with pytest.raises(BaseAgentSchemaError) as excinfo:
            ConcreteAgent(
                agent_name="my_agent",
                system_prompt="prompt",
                output_type=_OutputWithAnyField,
                model=test_model,
            )
        msg = str(excinfo.value)
        assert "my_agent" in msg
        assert "_OutputWithAnyField" in msg
        assert "'payload'" in msg
        assert "Any" in msg
        # Helpful hint with concrete remediation
        assert "Narrow" in msg or "container" in msg

    def test_lists_multiple_offending_fields(self, test_model):
        from orqest.agents.base_agent import BaseAgentSchemaError

        with pytest.raises(BaseAgentSchemaError) as excinfo:
            ConcreteAgent(
                agent_name="multi",
                system_prompt="prompt",
                output_type=_OutputWithMultipleAnyFields,
                model=test_model,
            )
        msg = str(excinfo.value)
        assert "'foo'" in msg and "'bar'" in msg

    def test_accepts_concrete_output_types(self, test_model):
        # SimpleOutput has only `text: str` — should construct cleanly.
        agent = ConcreteAgent(
            agent_name="ok",
            system_prompt="prompt",
            output_type=SimpleOutput,
            model=test_model,
        )
        assert agent.output_type is SimpleOutput

    def test_accepts_any_inside_containers(self, test_model):
        # list[Any] and dict[str, Any] serialize to typed arrays/objects —
        # providers accept these. Only top-level Any is the killer.
        agent = ConcreteAgent(
            agent_name="containers",
            system_prompt="prompt",
            output_type=_OutputWithAnyInsideContainer,
            model=test_model,
        )
        assert agent.output_type is _OutputWithAnyInsideContainer

    def test_skips_validation_for_non_basemodel_output_type(self, test_model):
        # str/int/bool scalar output types skip the check (there's no
        # model_fields to inspect, and providers accept scalar outputs).
        class StringAgent(BaseAgent["GlobalState", str]):
            async def _run_implementation(self, state, **kwargs):
                result = await self.call_model("x", state)
                return result.output

        agent = StringAgent(
            agent_name="scalar",
            system_prompt="prompt",
            output_type=str,  # type: ignore[arg-type]
            model=test_model,
        )
        assert agent.output_type is str
