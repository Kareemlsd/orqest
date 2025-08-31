"""Example of using the error handling system in Orqest with lifecycle hooks.

This example demonstrates how to use the error handling system in Orqest,
including creating and handling errors, using error context, formatting
error messages, and using lifecycle hooks for error handling.
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from pydantic import BaseModel
from orqest.agents.base_agent import BaseAgent, NoValidResponse
from orqest.agents.hooks import HookPoint, Middleware, hook
from examples.agents import GlobalState
from orqest.errors import (
    ErrorSeverity,
    ErrorCategory,
    ErrorContext,
    OrqestError,
    AgentError,
    ToolError,
    format_error_message
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(Middleware):
    """Middleware that handles errors during agent execution."""
    
    def __init__(self, logger=None):
        """Initialize the error handling middleware.
        
        Args:
            logger: Logger to use for logging errors. Defaults to the module logger.
        """
        self.logger = logger or logging.getLogger(__name__)
    
    async def on_error(self, error: Exception, state: BaseModel, operation: str, **kwargs) -> Any:
        """Execute when an error occurs during the agent's execution.
        
        Args:
            error: The exception that occurred.
            state: The state that was being processed.
            operation: The operation being performed when the error occurred.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The result to be returned from the agent's method, or re-raises the error.
        """
        self.logger.error(f"Error in {operation}: {error}")
        
        # Log detailed information about the error
        if isinstance(error, OrqestError):
            formatted_message = format_error_message(error)
            self.logger.error(f"Formatted error message: {formatted_message}")
        
        # Return the NoValidResponse if it's provided in kwargs
        response = kwargs.get("response")
        if response and isinstance(response, NoValidResponse):
            return response
        
        # Otherwise, re-raise the error
        raise error

class ErrorDemoAgent(BaseAgent[GlobalState]):
    """Demo agent that showcases error handling in Orqest using lifecycle hooks."""
    
    def __init__(self):
        """Initialize the error demo agent."""
        super().__init__(
            agent_name="error_demo_agent",
            output_type=GlobalState | NoValidResponse,
            system_prompt="You are a demo agent for error handling.",
            retries=1,
            tools=[
                self._simulate_tool_error,
            ]
        )
        
        # Add error handling middleware
        self.use_middleware(ErrorHandlingMiddleware())
        
        # Add a direct hook for error handling
        self.add_hook(HookPoint.ON_ERROR, self._log_error_details)
    
    async def _log_error_details(self, error: Exception, state: BaseModel, operation: str, **kwargs) -> Any:
        """Log detailed information about errors.
        
        Args:
            error: The exception that occurred.
            state: The state that was being processed.
            operation: The operation being performed when the error occurred.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The result to be returned from the agent's method, or re-raises the error.
        """
        logger.error(f"Custom error hook: Error in {operation}: {error}")
        
        # Return the NoValidResponse if it's provided in kwargs
        response = kwargs.get("response")
        if response and isinstance(response, NoValidResponse):
            return response
        
        # Otherwise, let the middleware handle it
        return error
    
    async def _run_implementation(self, state: GlobalState, **kwargs) -> GlobalState:
        """Implement the agent's run logic with error handling demonstrations.
        
        Args:
            state: The current state.
            **kwargs: Additional keyword arguments.
            
        Returns:
            Updated state or NoValidResponse if an error occurs.
        """
        # Get the error type to simulate from the state
        error_type = state.get_latest_user_message() or "none"
        
        # Simulate different error scenarios based on the error type
        if error_type.lower() == "agent":
            # Simulate an agent error
            raise AgentError(
                message="Simulated agent error",
                severity=ErrorSeverity.ERROR,
                context=self._create_error_context(
                    operation="_run_implementation",
                    details={"error_type": "agent"}
                )
            )
        elif error_type.lower() == "tool":
            # Simulate a tool error by calling the tool
            await self._simulate_tool_error("This will fail")
        elif error_type.lower() == "validation":
            # Simulate a validation error
            state.add_message("assistant", "Simulating a validation error")
            return state
        else:
            # No error, just return the state with a success message
            state.add_message("assistant", "No error was simulated")
            return state
    
    async def _process_response_implementation(self, response, state: GlobalState, **kwargs) -> GlobalState:
        """Process the agent response.
        
        This is a required method for BaseAgent subclasses, but we don't use it
        in this example since we're not actually calling the LLM.
        
        Args:
            response: The response from the agent.
            state: The current state.
            **kwargs: Additional keyword arguments.
            
        Returns:
            Updated state.
        """
        return state
    
    async def _simulate_tool_error(self, input_text: str) -> Dict[str, Any]:
        """Simulate a tool error.
        
        Args:
            input_text: The input text.
            
        Returns:
            Never returns, always raises a ToolError.
            
        Raises:
            ToolError: Always raises this error.
        """
        # Create error details
        details = {
            "input_text": input_text,
            "tool_name": "_simulate_tool_error"
        }
        
        # Create and raise a ToolError
        raise ToolError(
            message="Simulated tool error",
            severity=ErrorSeverity.ERROR,
            context=self._create_error_context(
                operation="_simulate_tool_error",
                details=details
            )
        )

async def demonstrate_error_handling(error_type: Optional[str] = None):
    """Demonstrate error handling with different error types using lifecycle hooks.
    
    Args:
        error_type: The type of error to simulate (agent, tool, validation, or None).
    """
    # Create the agent
    agent = ErrorDemoAgent()
    
    # Create a state with the error type as the user message
    state = GlobalState()
    if error_type:
        state.add_message("user", error_type)
    
    # Run the agent
    logger.info(f"Demonstrating error handling with error_type={error_type}")
    logger.info(f"Using lifecycle hooks for error handling")
    
    # The agent.run method will now use hooks for error handling
    result = await agent.run(state)
    
    # Check the result
    if isinstance(result, NoValidResponse):
        logger.info("Received NoValidResponse:")
        logger.info(f"  Error message: {result.error_message}")
        logger.info(f"  Error type: {result.error_type}")
        logger.info(f"  Agent name: {result.agent_name}")
        logger.info(f"  Operation: {result.operation}")
        logger.info(f"  This error was handled by the ON_ERROR hook")
    else:
        logger.info("Received valid response:")
        for message in result.messages:
            if message["role"] == "assistant":
                logger.info(f"  Assistant: {message['content']}")

async def main():
    """Run the error handling demonstrations."""
    # Demonstrate different error types
    await demonstrate_error_handling(None)  # No error
    await demonstrate_error_handling("agent")  # Agent error
    await demonstrate_error_handling("tool")  # Tool error
    await demonstrate_error_handling("validation")  # Validation error (no actual error)

if __name__ == "__main__":
    # Run the demonstrations
    asyncio.run(main())