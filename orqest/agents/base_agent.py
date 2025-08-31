"""Base class for Orqest agents."""
from abc import abstractmethod
import asyncio
import inspect
import logging
from typing import Any, Dict, List, Optional, Type, TypeVar, Union, Generic, Callable

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
from orqest.agents.hooks import HookRegistry, HookPoint, Middleware, hook

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
        hooks : Registry for lifecycle hooks
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
        self._hooks = HookRegistry()
        self._middleware: List[Middleware] = []
        
        # Register hooks from methods decorated with @hook
        self._register_decorated_hooks()
        
    def _register_decorated_hooks(self) -> None:
        """Register hooks from methods decorated with @hook."""
        for name, method in inspect.getmembers(self, inspect.ismethod):
            # Check if the method has hook attributes
            if hasattr(method, "_hook_point") and hasattr(method, "_hook_priority"):
                hook_point = getattr(method, "_hook_point")
                priority = getattr(method, "_hook_priority")
                self.add_hook(hook_point, method, priority)
                
    def add_hook(
        self, 
        hook_point: Union[HookPoint, str], 
        hook_func: Callable[..., Any], 
        priority: int = 0,
        name: Optional[str] = None
    ) -> None:
        """Add a hook to the agent.
        
        Args:
            hook_point: The hook point to register the hook for.
            hook_func: The hook function to register.
            priority: The priority of the hook (higher priority hooks are executed first).
            name: Optional name for the hook (defaults to the function name).
        """
        self._hooks.add_hook(hook_point, hook_func, priority, name)
        
    def remove_hook(self, hook_point: Union[HookPoint, str], name: str) -> bool:
        """Remove a hook from the agent.
        
        Args:
            hook_point: The hook point to remove the hook from.
            name: The name of the hook to remove.
            
        Returns:
            True if the hook was removed, False otherwise.
        """
        return self._hooks.remove_hook(hook_point, name)
        
    def use_middleware(self, middleware: Middleware) -> None:
        """Add middleware to the agent.
        
        Middleware provides a way to inject logic at multiple hook points in the agent lifecycle.
        
        Args:
            middleware: The middleware to add.
        """
        # Add middleware to the list
        self._middleware.append(middleware)
        
        # Register middleware methods as hooks
        if hasattr(middleware, "pre_run"):
            self.add_hook(HookPoint.PRE_RUN, middleware.pre_run)
            
        if hasattr(middleware, "post_run"):
            self.add_hook(HookPoint.POST_RUN, middleware.post_run)
            
        if hasattr(middleware, "pre_process_response"):
            self.add_hook(HookPoint.PRE_PROCESS_RESPONSE, middleware.pre_process_response)
            
        if hasattr(middleware, "post_process_response"):
            self.add_hook(HookPoint.POST_PROCESS_RESPONSE, middleware.post_process_response)
            
        if hasattr(middleware, "on_error"):
            self.add_hook(HookPoint.ON_ERROR, middleware.on_error)
        
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
        details: Optional[Dict[str, Any]] = None,
        state: Optional[BaseModel] = None
    ) -> NoValidResponse:
        """Handle an agent error and return a NoValidResponse.
        
        Args:
            error: The exception that occurred.
            operation: The operation being performed when the error occurred.
            severity: The severity level of the error.
            details: Additional details about the error context.
            state: The state that was being processed when the error occurred.
            
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
        
        # Create a NoValidResponse with error information
        response = NoValidResponse(
            messages=[error_message],
            error_message=str(error),
            error_type=type(error).__name__,
            agent_name=self.agent_name,
            operation=operation
        )
        
        # Execute on_error hooks if state is provided
        if state:
            try:
                # Execute on_error hooks
                hook_result = await self._hooks.execute_hooks(
                    HookPoint.ON_ERROR,
                    error,
                    state,
                    operation=operation,
                    details=details,
                    response=response
                )
                
                # If a hook returned a value, use it as the response
                if hook_result is not None:
                    return hook_result
            except Exception as hook_error:
                # Log the error from the hook
                logger.error(f"Error executing on_error hooks: {str(hook_error)}")
        
        return response

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

    async def run(self, state: BaseModel, **kwargs: Any) -> OutputT:
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
            # Execute pre_run hooks
            modified_state = await self._hooks.execute_hooks(
                HookPoint.PRE_RUN,
                state,
                **kwargs
            )
            
            # Run the agent implementation
            result = await self._run_implementation(modified_state, **kwargs)
            
            # Execute post_run hooks
            modified_result = await self._hooks.execute_hooks(
                HookPoint.POST_RUN,
                modified_state,
                result,
                **kwargs
            )
            
            return modified_result
            
        except Exception as e:
            # Handle the error using the standardized error handling
            return self._handle_agent_error(
                error=e,
                operation="run",
                severity=ErrorSeverity.ERROR,
                details=kwargs.get("details"),
                state=state
            )
    
    async def _process_agent_response(
        self,
        response: Any,
        state: BaseModel,
        **kwargs: Any
    ) -> OutputT:
        """Process the agent response and return an updated state.

        This method executes hooks before and after the agent's _process_response_implementation method.
        Subclasses should override _process_response_implementation, not this method.

        Args:
            response: The response from the agent.
            state: The current state of the agent.
            **kwargs: Additional keyword arguments.

        Returns:
            Updated state after processing the response.
        """
        try:
            # Execute pre_process_response hooks
            modified_response, modified_state = await self._hooks.execute_hooks(
                HookPoint.PRE_PROCESS_RESPONSE,
                response,
                state,
                **kwargs
            )
            
            # Process the response implementation
            result = await self._process_response_implementation(modified_response, modified_state, **kwargs)
            
            # Execute post_process_response hooks
            modified_result = await self._hooks.execute_hooks(
                HookPoint.POST_PROCESS_RESPONSE,
                modified_response,
                modified_state,
                result,
                **kwargs
            )
            
            return modified_result
            
        except Exception as e:
            # Handle the error using the standardized error handling
            return self._handle_agent_error(
                error=e,
                operation="_process_agent_response",
                severity=ErrorSeverity.ERROR,
                details=kwargs.get("details"),
                state=state
            )

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

    @abstractmethod
    async def _process_response_implementation(
            self,
            response: Any,
            state: BaseModel,
            **kwargs: Any
    ) -> OutputT:
        """Implement the agent's response processing logic.

        This method should be implemented by subclasses to process the agent response and
        return an updated state.

        Args:
            response: The response from the agent.
            state: The current state of the agent.
            **kwargs: Additional keyword arguments.

        Returns:
            Updated state after processing the response.
        """
        ...

