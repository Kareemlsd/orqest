"""Base class for Orqest agents."""
from abc import abstractmethod
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar, Union, Generic

from langchain_core.documents import Document
from pydantic_ai import Tool, Agent, RunContext, ModelRetry
from pydantic import BaseModel, Field

from orqest.utils.llm_model import model as get_model

logger = logging.getLogger(__name__)

# Type variable for the output state
OutputT = TypeVar("OutputT", bound=BaseModel)

class NoValidResponse(BaseModel):
    """No valid response from the agent"""
    messages: str = Field(
        description="No valid response from the agent",
        default_factory=list
    )


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
        model : The LLM to use for agent execution (initialized lazily)
    """

    def __init__(
            self,
            agent_name: str,
            system_prompt: str,
            output_type: Type[OutputT] | Type[Union[OutputT, NoValidResponse]],
            retries: int = 3,
            tools: Optional[List[Tool]] = None,
    ):
        """Initialize the BaseAgent instance."""
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.output_type = output_type
        self.retries = retries
        self.tools = [Tool(tool) for tool in tools] if tools else []
        self._model = None
        self._agent = None

    @property
    def model(self):
        """Initialize and return the LLM model."""
        if self._model is None:
            self._model = get_model()
        return self._model

    @property
    def agent(self):
        """Initialize and return the agent."""
        if self._agent is None:
            self._agent = Agent(
                name=self.agent_name,
                system_prompt=self.system_prompt,
                output_type=self.output_type,
                tools=self.tools,
                model=self.model,
            )
        return self._agent

    @abstractmethod
    async def run(self, state: BaseModel) -> OutputT:
        """Run the agent with the provided state.

        This method should be implemented by subclasses to define how the agent processes
        the state and returns an updated state.

        Args:
            state: The current state of the agent.

        Returns:
            Updated state after the agent has processed it.
        """

    @abstractmethod
    async def _process_agent_response(
            self,
            response: Any,
            state: BaseModel,
            **kwargs: Any
    ) -> OutputT:
        """Process the agent response and return an updated state.

        This method should be implemented by subclasses to process the agent response and
        return an updated state.

        Args:
            response: The response from the agent.
            state: The current state of the agent.

        Returns:
            Updated state after processing the response.
        """
        ...

