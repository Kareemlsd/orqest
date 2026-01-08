"""Base class for Orqest agents.

This module provides the foundational BaseAgent class that all Orqest agents
should inherit from. It handles common agent functionality including:
- LLM model initialization and management
- Tool and toolset registration
- Message history processing and truncation
- Standardized run execution with error handling

Example:
    class MyCustomAgent(BaseAgent[MyState, MyOutput]):
        async def _run_implementation(self, state: MyState, **kwargs) -> MyOutput:
            # Custom agent logic here
            pass
"""
from abc import abstractmethod
import logging
from typing import Any, List, Optional, Type, TypeVar, Union, Generic, Callable

from pydantic import BaseModel
from pydantic_ai import Tool, Agent
from pydantic_ai.messages import ModelMessage, ToolReturnPart, ToolCallPart

from orqest.utils.llm_model import model as get_model

logger = logging.getLogger(__name__)

# Type variable for the input state, must be a Pydantic BaseModel
StateT = TypeVar("StateT", bound=BaseModel)
# Type variable for the output type, must be a Pydantic BaseModel
OutputT = TypeVar("OutputT", bound=BaseModel)

# Type alias for history processor functions that transform message lists
HistoryProcessor = Callable[[List[ModelMessage]], List[ModelMessage]]

class BaseAgent(Generic[StateT, OutputT]):
    """Abstract base class for creating Orqest agents.

    This class provides a standardized interface for building AI agents with
    configurable tools, history processing, and LLM model integration. Subclasses
    must implement the `_run_implementation` method to define custom agent behavior.

    Type Parameters:
        StateT: The type of the input state, must be a Pydantic BaseModel.
        OutputT: The type of the output, must be a Pydantic BaseModel.

    Attributes:
        agent_name: A human-readable name for the agent.
        system_prompt: The system prompt that guides the agent's behavior.
        output_type: The Pydantic model class for structured output.
        retries: Number of retry attempts for failed operations.
        deps_type: Optional dependency type for the agent.
        truncated_history: Maximum number of recent messages to retain in history.
        tools: List of Tool instances available to the agent.
        toolsets: List of toolset objects providing additional tools.

    Example:
        >>> class SummaryAgent(BaseAgent[DocumentState, SummaryOutput]):
        ...     async def _run_implementation(self, state, **kwargs):
        ...         result = await self.agent.run(state.document_text)
        ...         return result.output
    """

    def __init__(
            self,
            agent_name: str,
            system_prompt: str,
            output_type: Type[OutputT],
            *,
            retries: int = 3,
            deps_type: Optional[Any] = None,
            tools: Optional[List[Tool]] = None,
            toolsets: Optional[List[Any]] = None,
            agent: Optional[Agent] = None,
            model: Optional[Callable] = None,
            truncated_history: int = 100,
            history_processors: Optional[Union[HistoryProcessor, List[HistoryProcessor]]] = None,
    ):
        """Initialize the BaseAgent instance.

        Args:
            agent_name: A descriptive name for the agent, used for logging and identification.
            system_prompt: The system prompt that defines the agent's persona and instructions.
            output_type: The Pydantic model class that defines the structure of the agent's output.
            retries: Number of times to retry failed LLM calls. Defaults to 3.
            deps_type: Optional type for dependencies that will be injected into the agent.
            tools: Optional list of Tool instances or callables to register with the agent.
            toolsets: Optional list of toolset objects that provide collections of tools.
            agent: Optional pre-configured Agent instance. If not provided, one will be created.
            model: Optional callable that returns an LLM model. If not provided, uses default.
            truncated_history: Maximum number of recent messages to keep in conversation history.
                Defaults to 100.
            history_processors: Optional single processor or list of processors for transforming
                message history. If not provided, uses the default `keep_recent_messages` processor.
        """
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.output_type = output_type
        self.retries = retries
        self.deps_type = deps_type
        self.truncated_history = truncated_history

        self.tools: List[Tool] = []
        if tools:
            for t in tools:
                self.tools.append(t if isinstance(t, Tool) else Tool(t))

        self.toolsets = list(toolsets) if toolsets else []

        # History processors
        if history_processors is None:
            self._history_processors: List[HistoryProcessor] = [self.keep_recent_messages]
        elif isinstance(history_processors, list):
            self._history_processors = history_processors
        else:
            self._history_processors = [history_processors]

        self._model = model
        self._agent = agent

    @property
    def model(self):
        """Lazily initialize and return the LLM model.

        Returns:
            The LLM model instance. If no model was provided during initialization,
            creates one using the default `get_model()` function from orqest.utils.
        """
        if self._model is None:
            self._model = get_model()
        return self._model

    @property
    def agent(self):
        """Lazily initialize and return the pydantic-ai Agent.

        Creates a new Agent instance if one was not provided during initialization,
        configuring it with the agent's name, system prompt, output type, tools,
        toolsets, retry settings, model, and history processors.

        Returns:
            Agent: The configured pydantic-ai Agent instance.
        """
        if self._agent is None:
            self._agent = Agent(
                name=self.agent_name,
                system_prompt=self.system_prompt,
                output_type=self.output_type,
                tools=self.tools,
                toolsets=self.toolsets,
                retries=self.retries,
                model=self.model,
                history_processors=self._history_processors
            )
        return self._agent

    async def run(self, state: StateT, **kwargs: Any) -> Union[OutputT, None]:
        """Execute the agent with the provided state.

        This is the main entry point for running the agent. It wraps the
        `_run_implementation` method with error handling and logging.

        Note:
            Subclasses should override `_run_implementation`, not this method.

        Args:
            state: The current state object containing input data for the agent.
            **kwargs: Additional keyword arguments passed to `_run_implementation`.

        Returns:
            The agent's output as defined by OutputT, or None if an exception occurs.

        Raises:
            Exceptions are caught and logged, returning None instead of propagating.
        """
        try:
            # Run the agent's customized run implementation
            result = await self._run_implementation(state, **kwargs)
            return result

        except Exception as e:
            logger.exception(e)
            return None


    @abstractmethod
    async def _run_implementation(self, state: StateT, **kwargs: Any) -> OutputT:
        """Implement the agent's core run logic.

        This abstract method must be implemented by subclasses to define how the
        agent processes the input state and produces output. This is where the
        main agent logic should reside.

        Args:
            state: The current state object containing input data for the agent.
            **kwargs: Additional keyword arguments for customizing execution.

        Returns:
            The processed output matching the OutputT type specification.

        Example:
            >>> async def _run_implementation(self, state, **kwargs):
            ...     result = await self.agent.run(state.prompt)
            ...     return result.output
        """

    def keep_recent_messages(self, messages: List[ModelMessage]) -> List[ModelMessage]:
        """Process message history to retain only recent messages.

        This default history processor maintains a sliding window of recent messages
        while preserving the first message (typically containing the system prompt).
        It also handles repair of tool-call groupings to ensure tool calls and their
        responses are kept together.

        The processor performs the following operations:
        1. Updates the system prompt in the first message to the current value
        2. Truncates to keep only the most recent `truncated_history` messages
        3. Repairs tool-call groupings if truncation splits a tool call from its response
        4. Ensures the first message is always preserved

        Args:
            messages: The full list of conversation messages to process.

        Returns:
            A processed list of messages containing:
            - The first message (with updated system prompt)
            - The most recent messages up to `truncated_history` limit
            - Any additional messages needed to maintain tool-call integrity
        """
        if not messages:
            return messages

        # Safely set system prompt if structure matches expectation
        try:
            if messages[0].parts and hasattr(messages[0].parts[0], "content"):
                messages[0].parts[0].content = self.system_prompt
        except Exception:
            logger.debug("Could not overwrite system prompt in history processor", exc_info=True)

        n = max(1, self.truncated_history)
        truncated = messages[-n:] if len(messages) > n else messages

        # Repair tool-call groupings if needed
        if truncated:
            try:
                first_part = truncated[0].parts[0] if truncated[0].parts else None
                if isinstance(first_part, ToolReturnPart):
                    # walk backward to include matching ToolCallPart
                    start_idx = len(messages) - len(truncated) - 1
                    for i in range(start_idx, -1, -1):
                        part0 = messages[i].parts[0] if messages[i].parts else None
                        if isinstance(part0, ToolCallPart):
                            truncated = messages[i:]
                            break
            except Exception:
                logger.debug("Tool-call repair failed", exc_info=True)

        # Ensure first message preserved
        if len(truncated) <= 1:
            return [messages[0]]
        return [messages[0]] + truncated[1:]


if __name__ == "__main__":
    pass