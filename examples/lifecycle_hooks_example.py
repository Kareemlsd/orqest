"""Example demonstrating the Agent Lifecycle Hooks feature.

This example shows how to use the Agent Lifecycle Hooks feature to inject custom logic
at different points in an agent's lifecycle.
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from pydantic import BaseModel, Field

from orqest.agents.base_agent import BaseAgent, NoValidResponse
from orqest.agents.hooks import HookPoint, Middleware, hook
from orqest.errors import ErrorSeverity

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ExampleState(BaseModel):
    """Example state for the agent."""
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    results: List[str] = Field(default_factory=list)
    
    def add_message(self, role: str, content: str) -> None:
        """Add a message to the state."""
        self.messages.append({"role": role, "content": content})
    
    def get_latest_user_message(self) -> Optional[str]:
        """Get the latest user message."""
        for message in reversed(self.messages):
            if message["role"] == "user":
                return message["content"]
        return None


class LoggingMiddleware(Middleware):
    """Middleware that logs agent lifecycle events."""
    
    async def pre_run(self, state: BaseModel, **kwargs) -> BaseModel:
        """Execute before the agent's run method is called."""
        logger.info(f"Starting agent run with state: {state}")
        return state
    
    async def post_run(self, state: BaseModel, result: Any, **kwargs) -> Any:
        """Execute after the agent's run method is called."""
        logger.info(f"Finished agent run with result: {result}")
        return result
    
    async def pre_process_response(self, response: Any, state: BaseModel, **kwargs) -> tuple[Any, BaseModel]:
        """Execute before the agent's _process_response_implementation method is called."""
        logger.info(f"Processing response: {response}")
        return response, state
    
    async def post_process_response(self, response: Any, state: BaseModel, result: Any, **kwargs) -> Any:
        """Execute after the agent's _process_response_implementation method is called."""
        logger.info(f"Finished processing response with result: {result}")
        return result
    
    async def on_error(self, error: Exception, state: BaseModel, operation: str, **kwargs) -> Any:
        """Execute when an error occurs during the agent's execution."""
        logger.error(f"Error in {operation}: {error}")
        return kwargs.get("response", None)


class TimingMiddleware(Middleware):
    """Middleware that measures the time taken by agent operations."""
    
    async def pre_run(self, state: BaseModel, **kwargs) -> BaseModel:
        """Execute before the agent's run method is called."""
        kwargs["start_time"] = asyncio.get_event_loop().time()
        return state
    
    async def post_run(self, state: BaseModel, result: Any, **kwargs) -> Any:
        """Execute after the agent's run method is called."""
        start_time = kwargs.get("start_time")
        if start_time:
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"Agent run took {elapsed:.2f} seconds")
        return result


class ExampleAgent(BaseAgent[ExampleState]):
    """Example agent that uses lifecycle hooks."""
    
    def __init__(self):
        super().__init__(
            agent_name="example_agent",
            system_prompt="You are an example agent.",
            output_type=ExampleState,
            retries=2
        )
        
        # Add middleware
        self.use_middleware(LoggingMiddleware())
        self.use_middleware(TimingMiddleware())
        
        # Add direct hooks
        self.add_hook(HookPoint.PRE_RUN, self.validate_state)
        
    async def validate_state(self, state: ExampleState, **kwargs) -> ExampleState:
        """Validate the state before running the agent."""
        if not state.messages:
            logger.warning("State has no messages, adding a default message")
            state.add_message("user", "Hello, agent!")
        return state
    
    @hook(HookPoint.POST_RUN)
    async def add_completion_message(self, state: ExampleState, result: ExampleState, **kwargs) -> ExampleState:
        """Add a completion message to the result."""
        result.results.append("Agent run completed successfully")
        return result
    
    async def _run_implementation(self, state: ExampleState, **kwargs) -> ExampleState:
        """Implement the agent's run logic."""
        logger.info(f"Running example agent with state: {state}")
        
        # Get the latest user message
        user_message = state.get_latest_user_message() or "No user message"
        
        # Add a result
        state.results.append(f"Processed user message: {user_message}")
        
        # Add an assistant message
        state.add_message("assistant", f"I received your message: {user_message}")
        
        return state
    
    async def _process_response_implementation(
        self,
        response: Any,
        state: ExampleState,
        **kwargs
    ) -> ExampleState:
        """Implement the agent's response processing logic."""
        logger.info(f"Processing response: {response}")
        
        # Add a result
        state.results.append(f"Processed response: {response}")
        
        return state


async def run_example():
    """Run the example."""
    # Create an agent
    agent = ExampleAgent()
    
    # Create a state
    state = ExampleState()
    state.add_message("user", "Hello, agent! This is a test message.")
    
    # Run the agent
    result = await agent.run(state)
    
    # Print the results
    print("\nResults:")
    for result_item in result.results:
        print(f"- {result_item}")
    
    # Print the messages
    print("\nMessages:")
    for message in result.messages:
        print(f"- {message['role']}: {message['content']}")


if __name__ == "__main__":
    asyncio.run(run_example())