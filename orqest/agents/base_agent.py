"""Base class for orqest agents.

Provides BaseAgent[StateT, OutputT] — the abstract foundation that all orqest
agents inherit from. Subclasses implement _run_implementation() to define their
logic; everything else (model wiring, agent construction, history processing)
is handled here.
"""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace as dc_replace
from functools import partial
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    AgentStreamEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolReturnPart,
    UserContent,
)
from pydantic_ai.models import Model
from pydantic_ai.result import StreamedRunResult
from pydantic_ai.run import AgentRunResult
from pydantic_ai.settings import ModelSettings

from orqest.agents.context_manager import ContextManager
from orqest.utils.llm_model import resolve_model

Prompt = str | Sequence[UserContent]

StateT = TypeVar("StateT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


def keep_recent_messages(
    messages: list[ModelMessage],
    *,
    max_messages: int = 100,
) -> list[ModelMessage]:
    """Truncate message history while preserving the first message and turn integrity.

    Returns a new list — never mutates the input.

    The first message is always preserved because it typically contains the initial
    user prompt that establishes context. When truncation would split a
    request/response pair (tool call followed by tool return), the preceding
    response is included to maintain a valid message sequence.
    """
    if not messages or max_messages <= 0:
        return list(messages)

    n = max(1, max_messages)
    if len(messages) <= n:
        return list(messages)

    truncated = list(messages[-n:])

    # If truncation split a request/response pair, include the preceding response.
    # A ModelRequest right at the boundary that follows a ModelResponse means we
    # cut in the middle of a tool-call turn.
    boundary_idx = len(messages) - n
    first = truncated[0]
    if isinstance(first, ModelRequest) and boundary_idx > 0:
        preceding = messages[boundary_idx - 1]
        if isinstance(preceding, ModelResponse):
            truncated = [preceding] + truncated

    # Always preserve the first message in the full history.
    if truncated[0] is not messages[0]:
        return [messages[0]] + truncated

    return truncated


def budget_tool_results(
    messages: list[ModelMessage],
    *,
    max_result_chars: int = 20_000,
    preview_chars: int = 2_000,
) -> list[ModelMessage]:
    """Truncate oversized ToolReturnPart content in message history.

    Walks all messages, finds ToolReturnPart instances with content
    exceeding max_result_chars, and replaces with a preview prefix
    plus truncation notice. Returns a new list — never mutates input.
    """
    result: list[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            new_parts = []
            modified = False
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    content_str = str(part.content)
                    if len(content_str) > max_result_chars:
                        truncated = (
                            content_str[:preview_chars]
                            + f"\n\n[TRUNCATED — {len(content_str)} chars total. "
                            f"Full result was too large for context window.]"
                        )
                        new_parts.append(dc_replace(part, content=truncated))
                        modified = True
                    else:
                        new_parts.append(part)
                else:
                    new_parts.append(part)
            if modified:
                result.append(dc_replace(msg, parts=new_parts))
            else:
                result.append(msg)
        else:
            result.append(msg)
    return result


class BaseAgent(Generic[StateT, OutputT]):
    """Abstract base class for orqest agents.

    Generic over StateT (input state, a Pydantic model) and OutputT (output, a
    Pydantic model). Subclasses must implement _run_implementation().

    The model parameter is required so that each agent explicitly declares its
    provider — two agents in the same process can use different models without
    conflict.
    """

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        output_type: type[OutputT],
        *,
        model: Model | str,
        api_key: str | None = None,
        retries: int = 3,
        tools: list[Tool] | None = None,
        toolsets: list[Any] | None = None,
        truncated_history: int = 100,
        history_processors: list | None = None,
        result_budget: int | None = 20_000,
        context_manager: ContextManager | None = None,
        model_settings: ModelSettings | None = None,
        confidence_protocol: Any = None,
    ):
        """Initialize the agent.

        Args:
            agent_name: Name for logging and identification.
            system_prompt: System prompt guiding agent behavior.
            output_type: Pydantic model class for structured output.
            model: A pydantic-ai Model instance, or a 'provider:model_id' string.
            api_key: Required when model is a string; passed to the provider.
            retries: Retry attempts for failed LLM calls.
            tools: Individual Tool instances to register.
            toolsets: Toolset objects providing collections of tools.
            truncated_history: Max recent messages kept by the default history processor.
            history_processors: Custom processors; defaults to keep_recent_messages.
            result_budget: Max chars for tool result content before truncation.
                None disables budgeting. Default 20,000.
            context_manager: Optional ContextManager for token-aware compaction.
                When present, its compact method is prepended as the first
                history processor.
            model_settings: Optional pydantic-ai ``ModelSettings`` applied to
                every model call (e.g. ``ModelSettings(temperature=0.0,
                seed=42)``). Default ``None`` preserves provider defaults.
        """
        if isinstance(model, str):
            if api_key is None:
                raise ValueError(
                    "api_key is required when model is a string name. "
                    "Pass api_key explicitly or provide a Model instance instead."
                )
            self._model = resolve_model(model, api_key=api_key)
        elif isinstance(model, Model):
            self._model = model
        else:
            raise TypeError(
                f"model must be a pydantic-ai Model instance or a 'provider:model_id' string, "
                f"got {type(model).__name__}"
            )

        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.output_type = output_type
        self.retries = retries
        self.truncated_history = truncated_history
        self.model_settings = model_settings

        self.tools: list[Tool] = [
            t if isinstance(t, Tool) else Tool(t) for t in (tools or [])
        ]
        self.toolsets = list(toolsets) if toolsets else []

        if history_processors is not None:
            self._history_processors = list(history_processors)
        else:
            self._history_processors = [
                partial(keep_recent_messages, max_messages=truncated_history)
            ]

        if result_budget is not None:
            self._history_processors.insert(
                0, partial(budget_tool_results, max_result_chars=result_budget)
            )

        if context_manager is not None:
            self._history_processors.insert(0, context_manager.compact)

        self._confidence_protocol = confidence_protocol
        self._agent: Agent | None = None

    @property
    def model(self) -> Model:
        """The resolved pydantic-ai Model instance."""
        return self._model

    @property
    def agent(self) -> Agent:
        """Lazily constructed pydantic-ai Agent."""
        if self._agent is None:
            self._agent = Agent(
                name=self.agent_name,
                system_prompt=self.system_prompt,
                output_type=self.output_type,
                tools=self.tools,
                toolsets=self.toolsets,
                retries=self.retries,
                model=self._model,
                history_processors=self._history_processors,
                model_settings=self.model_settings,
            )
        return self._agent

    async def call_model(self, prompt: Prompt, state: StateT) -> AgentRunResult:
        """Run the pydantic-ai agent with conversation history from state.

        Passes state.message_history into Agent.run() and stores the updated
        history back on state after the run. This is the recommended way to
        call the LLM from _run_implementation() when you want multi-turn
        conversation support.

        For stateless one-shot calls, use self.agent.run() directly instead.
        """
        history = getattr(state, "message_history", None) or None
        result = await self.agent.run(prompt, message_history=history)
        if hasattr(state, "message_history"):
            state.message_history = result.all_messages()
        return result

    @asynccontextmanager
    async def call_model_stream(
        self, prompt: Prompt, state: StateT
    ) -> AsyncIterator[StreamedRunResult]:
        """Stream the pydantic-ai agent with conversation history from state.

        Async context manager that wraps Agent.run_stream(). Yields a
        StreamedRunResult for full control over the stream. Updates
        state.message_history after the context exits (once the stream
        is consumed).

        This is the low-level streaming primitive — stream_text() and
        stream_output() are built on top of it.
        """
        history = getattr(state, "message_history", None) or None
        async with self.agent.run_stream(prompt, message_history=history) as streamed:
            yield streamed
        if hasattr(state, "message_history"):
            state.message_history = streamed.all_messages()

    async def stream_output(
        self, prompt: Prompt, state: StateT, *, debounce_by: float | None = None
    ) -> AsyncIterator[OutputT]:
        """Stream partial structured output from the LLM.

        Async generator yielding partial OutputT Pydantic model instances
        as the model produces them. Each yield is the latest validated
        partial of the structured output.

        Args:
            prompt: The user prompt to send.
            state: Conversation state — history is read and updated.
            debounce_by: Optional minimum interval (seconds) between yields.
        """
        kwargs: dict[str, Any] = {}
        if debounce_by is not None:
            kwargs["debounce_by"] = debounce_by
        async with self.call_model_stream(prompt, state) as streamed:
            async for partial in streamed.stream_output(**kwargs):
                yield partial

    async def stream_events(
        self, prompt: Prompt, state: StateT
    ) -> AsyncIterator[AgentStreamEvent]:
        """Stream all agent events including model responses and tool calls.

        Async generator yielding AgentStreamEvent instances as the agent runs.
        This includes model response tokens (PartStartEvent, PartDeltaEvent,
        PartEndEvent, FinalResultEvent) and tool execution events
        (FunctionToolCallEvent, FunctionToolResultEvent).

        Uses Agent.iter() under the hood for full node-by-node control,
        making tool calls visible during streaming.

        Args:
            prompt: The user prompt to send.
            state: Conversation state — history is read and updated.
        """
        history = getattr(state, "message_history", None) or None
        async with self.agent.iter(prompt, message_history=history) as agent_run:
            async for node in agent_run:
                if Agent.is_model_request_node(node):
                    async with node.stream(agent_run.ctx) as stream:
                        async for event in stream:
                            yield event
                elif Agent.is_call_tools_node(node):
                    async with node.stream(agent_run.ctx) as stream:
                        async for event in stream:
                            yield event
        if hasattr(state, "message_history"):
            state.message_history = agent_run.result.all_messages()

    async def run(self, state: StateT, **kwargs: Any) -> OutputT:
        """Execute the agent. Exceptions propagate to the caller."""
        return await self._run_implementation(state, **kwargs)

    async def run_enriched(
        self,
        state: StateT,
        *,
        confidence_protocol: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Execute the agent and pair its output with self-assessment.

        Returns :class:`~orqest.metacognition.EnrichedOutput[OutputT]`.
        Best-effort: a protocol that fails surfaces ``confidence=None``
        and a ``protocol_error`` in the metadata; the underlying output
        is always returned. Exceptions raised by ``_run_implementation``
        propagate, exactly like :meth:`run`.

        Args:
            state: The agent's state, same as ``run``.
            confidence_protocol: Per-call override of the agent-level
                default (set via constructor). When neither is provided,
                returns ``EnrichedOutput(output=...)`` with all
                metacognitive fields at their defaults.
            **kwargs: Forwarded to ``_run_implementation`` and to the
                protocol's ``enrich`` call.
        """
        from orqest.metacognition.enriched import EnrichedOutput

        output = await self._run_implementation(state, **kwargs)
        protocol = confidence_protocol or self._confidence_protocol
        if protocol is None:
            return EnrichedOutput(output=output)
        try:
            return await protocol.enrich(self, state, output, **kwargs)
        except Exception as exc:
            from loguru import logger as _logger

            _logger.debug(
                "ConfidenceProtocol {p} failed: {e}",
                p=getattr(protocol, "name", type(protocol).__name__),
                e=str(exc),
            )
            return EnrichedOutput(
                output=output,
                metadata={"protocol_error": type(exc).__name__},
            )

    @abstractmethod
    async def _run_implementation(self, state: StateT, **kwargs: Any) -> OutputT:
        """Implement the agent's core logic.

        Subclasses define how the input state is processed and what output is
        produced. Use self.agent to call the underlying pydantic-ai Agent.
        """
        ...
