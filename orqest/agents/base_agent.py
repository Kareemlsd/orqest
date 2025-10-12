"""Base class for Orqest agents."""
from abc import abstractmethod
import logging
from typing import Any, List, Optional, Type, TypeVar, Union, Generic, Callable

from pydantic import BaseModel
from pydantic_ai import Tool, Agent
from pydantic_ai.messages import ModelMessage, ToolReturnPart, ToolCallPart

from orqest.utils.llm_model import model as get_model

logger = logging.getLogger(__name__)

# Type variable for the output state
OutputT = TypeVar("OutputT", bound=BaseModel)

class BaseAgent(Generic[OutputT]):
    """Base class for Orqest agents.

    This class provides a common foundation for all agents defined in Orqest,
    allowing for easy creation and customization of different agent types.

    Attributes:
        agent_name : Name of the agent for logging and identification purposes.
        system_prompt : The system prompt that defines the agent's behavior.
        output_type : The type of the output state.
        retries : Number of retries for failed agent executions.
        tools : List of tools that the agent can use for execution.
        history_processor : Optional function to process the message history.
        deps_type : Optional Pydantic model defining dependencies required by the agent.
        model : The LLM to use for agent execution (initialized lazily)
        hooks : Registry for lifecycle hooks
    """

    def __init__(
            self,
            agent_name: str,
            system_prompt: str,
            output_type: Type[OutputT],
            retries: int = 3,
            deps_type: Optional[Type[BaseModel]] = None,
            tools: Optional[List[Tool]] = None,
            toolsets: Optional[List[Any]] = None,
            agent: Optional[Agent] = None,
            model: Optional[Callable] = None,
            truncated_history: int = 100,
            history_processors: Optional[
                Union[
                    Callable[[List[ModelMessage]], List[ModelMessage]],
                    List[Callable[[List[ModelMessage]], List[ModelMessage]]]
                ]
            ] = None
    ):
        """Initialize the BaseAgent instance."""
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.output_type = output_type
        self.retries = retries
        self.tools = [Tool(tool) for tool in tools] if tools else []
        self.toolsets = [toolset for toolset in toolsets] if toolsets else []
        self.deps_type = deps_type
        self.truncated_history = truncated_history
        self._history_processors = history_processors
        self._model = model
        self._agent = agent

        if self._history_processors is None:
            self._history_processors = [self.keep_recent_messages]
        else:
            self._history_processors = [*history_processors] if isinstance(history_processors, list) else [history_processors]

    @property
    def model(self):
        """Initialize and return the LLM model."""
        if self._model is None:
            self._model = get_model()
        return self._model

    @property
    def agent(self):
        """Initialize and return the agent. If no agent is provided, create a default one."""
        if self._agent is None:
            self._agent = Agent(
                name=self.agent_name,
                system_prompt=self.system_prompt,
                output_type=self.output_type,
                tools=self.tools,
                toolsets=self.toolsets,
                model=self.model,
                history_processors=self._history_processors
            )
        return self._agent

    async def run(self, state: BaseModel, **kwargs: Any) -> Union[OutputT, None]:
        """Run the agent with the provided state.

        This method executes hooks before and after the agent's _run_implementation method.
        Subclasses should override _run_implementation, not this method.

        Args:
            state: The current state of the agent.
            **kwargs: Additional keyword arguments to pass to the agent.

        Returns:
            Updated state after the agent has processed it.
        """
        try:
            # Run the agent's customized run implementation
            result = await self._run_implementation(state, **kwargs)
            return result
            
        except Exception as e:
            logger.exception(e)


    @abstractmethod
    async def _run_implementation(self, state: BaseModel, **kwargs: Any) -> OutputT:
        """Implement the agent's run logic.

        This method should be implemented by subclasses to define how the agent processes
        the state and returns an updated state.

        Args:
            state: The current state of the agent.
            **kwargs: Additional keyword arguments to pass to the agent.

        Returns:
            Updated state after the agent has processed it.
        """

    async def keep_recent_messages(
            self,
            messages: List[ModelMessage]
    ) -> List[ModelMessage]:
        """Keep only the most recent messages, ensuring tool-call groupings are intact."""
        # Always include the system prompt
        messages[0].parts[0].content = self.system_prompt

        # Truncate messages to the most recent `n`
        n = self.truncated_history
        truncated = messages[-n:] if len(messages) > n else messages

        # Repair tool-call groupings if needed
        if truncated and isinstance(truncated[0].parts[0], ToolReturnPart):
            for i in range(len(messages) - len(truncated) - 1, -1, -1):
                if isinstance(messages[i].parts[0], ToolCallPart):
                    truncated = messages[i:]
                    break

        # Ensure the first message is preserved
        return [messages[0]] + truncated[1:] if len(truncated) > 1 else [messages[0]]


if __name__ == "__main__":
    pass