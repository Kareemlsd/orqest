"""Example of using the error handling system in Orqest.

This example demonstrates how to use the error handling system in Orqest,
including creating and handling errors, using error context, and formatting
error messages.
"""
import asyncio
import logging
from typing import Dict, Any, Optional

from orqest.agents.base_agent import BaseAgent, NoValidResponse
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

class ErrorDemoAgent(BaseAgent[GlobalState]):
    """Demo agent that showcases error handling in Orqest."""
    
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
    
    async def run(self, state: GlobalState, **kwargs) -> GlobalState:
        """Run the agent with error handling demonstrations.
        
        Args:
            state: The current state.
            **kwargs: Additional keyword arguments.
            
        Returns:
            Updated state or NoValidResponse if an error occurs.
        """
        try:
            # Get the error type to simulate from the state
            error_type = state.get_latest_user_message() or "none"
            
            # Simulate different error scenarios based on the error type
            if error_type.lower() == "agent":
                # Simulate an agent error
                raise AgentError(
                    message="Simulated agent error",
                    severity=ErrorSeverity.ERROR,
                    context=self._create_error_context(
                        operation="run",
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
                
        except Exception as e:
            # Handle the error using the standardized error handling
            logger.error(f"Error in ErrorDemoAgent: {str(e)}")
            
            # Create error details
            details = {
                "error_type": type(e).__name__,
                "state_messages_count": len(state.messages) if hasattr(state, 'messages') else 0
            }
            
            # Return a NoValidResponse with error information
            return self._handle_agent_error(
                error=e,
                operation="run",
                severity=ErrorSeverity.ERROR,
                details=details
            )
    
    async def _process_agent_response(self, response, state: GlobalState, **kwargs) -> GlobalState:
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
    """Demonstrate error handling with different error types.
    
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
    result = await agent.run(state)
    
    # Check the result
    if isinstance(result, NoValidResponse):
        logger.info("Received NoValidResponse:")
        logger.info(f"  Error message: {result.error_message}")
        logger.info(f"  Error type: {result.error_type}")
        logger.info(f"  Agent name: {result.agent_name}")
        logger.info(f"  Operation: {result.operation}")
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