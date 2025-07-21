"""Base class for Orqest agents."""
from abc import abstractmethod
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar, Union, Generic

from langchain_core.documents import Document
from pydantic_ai import Tool, Agent, RunContext, ModelRetry
from pydantic import BaseModel, Field

from orqest.utils.llm_model import model as get_model
from orqest.errors import (
    ErrorSeverity,
    ErrorCategory,
    ErrorContext,
    OrqestError,
    AgentError,
    LLMError,
    format_error_message
)

logger = logging.getLogger(__name__)

# Type variable for the output state
OutputT = TypeVar("OutputT", bound=BaseModel)

class NoValidResponse(BaseModel):
    """No valid response from the agent.
    
    This class represents a state where an agent couldn't produce a valid response.
    It includes error information to help diagnose the issue.
    
    Attributes:
        messages: List of messages related to the error.
        error_message: Detailed error message explaining what went wrong.
        error_type: Type of error that occurred.
        agent_name: Name of the agent that encountered the error.
        operation: Operation being performed when the error occurred.
    """
    messages: List[str] = Field(
        description="List of messages related to the error",
        default_factory=list
    )
    error_message: str = Field(
        description="Detailed error message explaining what went wrong",
        default="No valid response from the agent"
    )
    error_type: str = Field(
        description="Type of error that occurred",
        default="AGENT_ERROR"
    )
    agent_name: Optional[str] = Field(
        description="Name of the agent that encountered the error",
        default=None
    )
    operation: Optional[str] = Field(
        description="Operation being performed when the error occurred",
        default=None
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
            deps_type: Optional[Type[BaseModel]] = None,
            tools: Optional[List[Tool]] = None,
    ):
        """Initialize the BaseAgent instance."""
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.output_type = output_type
        self.retries = retries
        self.tools = [Tool(tool) for tool in tools] if tools else []
        self.deps_type = deps_type
        self._model = None
        self._agent = None
        
    def _create_error_context(self, operation: str, details: Optional[Dict[str, Any]] = None) -> ErrorContext:
        """Create an error context for this agent.
        
        Args:
            operation: The operation being performed when the error occurred.
            details: Additional details about the error context.
            
        Returns:
            An ErrorContext instance with this agent's information.
        """
        return ErrorContext(
            agent_name=self.agent_name,
            operation=operation,
            details=details
        )
        
    def _handle_agent_error(
        self, 
        error: Exception, 
        operation: str, 
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Dict[str, Any]] = None
    ) -> NoValidResponse:
        """Handle an agent error and return a NoValidResponse.
        
        Args:
            error: The exception that occurred.
            operation: The operation being performed when the error occurred.
            severity: The severity level of the error.
            details: Additional details about the error context.
            
        Returns:
            A NoValidResponse instance with error information.
        """
        context = self._create_error_context(operation, details)
        
        # Create an AgentError
        agent_error = AgentError(
            message=str(error),
            severity=severity,
            context=context,
            exception=error
        )
        
        # Log the error
        error_message = format_error_message(agent_error)
        logger.error(error_message)
        
        # Return a NoValidResponse with error information
        return NoValidResponse(
            messages=[error_message],
            error_message=str(error),
            error_type=type(error).__name__,
            agent_name=self.agent_name,
            operation=operation
        )

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

