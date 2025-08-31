"""Example of using FlexibleOrchestratorAgent with different agents as tools and lifecycle hooks.

This example demonstrates how to use the FlexibleOrchestratorAgent to orchestrate
different types of agents without hardcoded references to specific agent types.
It also shows how to use lifecycle hooks to inject custom logic at different points
in an agent's lifecycle.
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from pydantic import BaseModel
from examples.agents import GlobalState, PlannerAgent
from examples.agents.flexible_orchestrator import FlexibleOrchestratorAgent
from orqest.agents.base_agent import BaseAgent, NoValidResponse
from orqest.agents.hooks import HookPoint, Middleware, hook

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LoggingMiddleware(Middleware):
    """Middleware that logs agent lifecycle events."""
    
    def __init__(self, logger=None):
        """Initialize the logging middleware."""
        self.logger = logger or logging.getLogger(__name__)
    
    async def pre_run(self, state: BaseModel, **kwargs) -> BaseModel:
        """Execute before the agent's run method is called."""
        self.logger.info(f"Starting agent run with state: {state}")
        return state
    
    async def post_run(self, state: BaseModel, result: Any, **kwargs) -> Any:
        """Execute after the agent's run method is called."""
        self.logger.info(f"Finished agent run with result: {result}")
        return result
    
    async def pre_process_response(self, response: Any, state: BaseModel, **kwargs) -> tuple[Any, BaseModel]:
        """Execute before the agent's _process_response_implementation method is called."""
        self.logger.info(f"Processing response: {response}")
        return response, state
    
    async def post_process_response(self, response: Any, state: BaseModel, result: Any, **kwargs) -> Any:
        """Execute after the agent's _process_response_implementation method is called."""
        self.logger.info(f"Finished processing response with result: {result}")
        return result
    
    async def on_error(self, error: Exception, state: BaseModel, operation: str, **kwargs) -> Any:
        """Execute when an error occurs during the agent's execution."""
        self.logger.error(f"Error in {operation}: {error}")
        return kwargs.get("response", None)


class TimingMiddleware(Middleware):
    """Middleware that measures the time taken by agent operations."""
    
    def __init__(self, logger=None):
        """Initialize the timing middleware."""
        self.logger = logger or logging.getLogger(__name__)
    
    async def pre_run(self, state: BaseModel, **kwargs) -> BaseModel:
        """Execute before the agent's run method is called."""
        kwargs["start_time"] = asyncio.get_event_loop().time()
        return state
    
    async def post_run(self, state: BaseModel, result: Any, **kwargs) -> Any:
        """Execute after the agent's run method is called."""
        start_time = kwargs.get("start_time")
        if start_time:
            elapsed = asyncio.get_event_loop().time() - start_time
            self.logger.info(f"Agent run took {elapsed:.2f} seconds")
        return result

class ResearchAgent(BaseAgent[GlobalState]):
    """Example research agent that can find information on topics using lifecycle hooks."""
    
    def __init__(
        self,
        agent_name: str = "research_agent",
        system_prompt: Optional[str] = None,
        output_type: Optional[type] = None,
        retries: int = 2,
        deps_type: Optional[type] = None,
        tools: Optional[List[Any]] = None,
    ):
        """Initialize the research agent."""
        # Set default values if not provided
        _system_prompt = system_prompt or """
            You are a research agent. Your goal is to find information on various topics.
            Provide detailed, accurate information based on your knowledge.
            """
        _output_type = output_type or (GlobalState | NoValidResponse)
        
        super().__init__(
            agent_name=agent_name,
            output_type=_output_type,
            system_prompt=_system_prompt,
            retries=retries,
            deps_type=deps_type or GlobalState,
            tools=tools
        )
        
        # Add middleware for logging and timing
        self.use_middleware(LoggingMiddleware(logger))
        self.use_middleware(TimingMiddleware(logger))
        
        # Add a direct hook for error handling
        self.add_hook(HookPoint.ON_ERROR, self._handle_research_error)
    
    async def _handle_research_error(self, error: Exception, state: BaseModel, operation: str, **kwargs) -> Any:
        """Handle errors during research operations.
        
        Args:
            error: The exception that occurred.
            state: The state that was being processed.
            operation: The operation being performed when the error occurred.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The updated state with an error message.
        """
        logger.error(f"Research error in {operation}: {error}")
        
        if isinstance(state, GlobalState):
            state.add_message("assistant", f"I encountered an error while researching: {str(error)}")
            return state
        
        # If we can't handle the error, let it propagate
        return error
    
    @hook(HookPoint.POST_RUN)
    async def log_research_completion(self, state: GlobalState, result: GlobalState, **kwargs) -> GlobalState:
        """Log the completion of research.
        
        Args:
            state: The original state.
            result: The result state after running the agent.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The result state.
        """
        logger.info(f"Research completed successfully")
        return result
    
    async def _run_implementation(self, state: GlobalState, **kwargs) -> GlobalState:
        """Implement the research agent's run logic.
        
        Args:
            state: The current state of the conversation.
            **kwargs: Additional keyword arguments to pass to the agent.
            
        Returns:
            Updated state after the agent has processed it.
        """
        # Get the user's query
        query = state.get_latest_user_message()
        
        # Create a prompt for the agent
        prompt = f"""
        Please research the following topic and provide detailed information:
        {query}
        
        Provide a comprehensive answer with key facts and insights.
        """
        
        # Log the operation
        logger.info(f"Running research agent with query: {query[:100]}...")
        
        # Execute the agent
        response = await self.agent.run(prompt, deps=state, message_history=state.chat_history, **kwargs)
        state.chat_history.extend(response.all_messages())
        
        # Process the response
        return await self._process_response_implementation(response, state)
    
    async def _process_response_implementation(self, response, state: GlobalState, **kwargs) -> GlobalState:
        """Process the agent response and update the state."""
        # Add the response to the state
        if hasattr(response, "content"):
            state.add_message("assistant", response.content)
        else:
            state.add_message("assistant", "I couldn't find any information on that topic.")
        
        return state

class SummaryAgent(BaseAgent[GlobalState]):
    """Example summary agent that can summarize text using lifecycle hooks."""
    
    def __init__(
        self,
        agent_name: str = "summary_agent",
        system_prompt: Optional[str] = None,
        output_type: Optional[type] = None,
        retries: int = 2,
        deps_type: Optional[type] = None,
        tools: Optional[List[Any]] = None,
    ):
        """Initialize the summary agent."""
        # Set default values if not provided
        _system_prompt = system_prompt or """
            You are a summary agent. Your goal is to summarize text into concise, clear points.
            Focus on extracting the key information and presenting it in a structured format.
            """
        _output_type = output_type or (GlobalState | NoValidResponse)
        
        super().__init__(
            agent_name=agent_name,
            output_type=_output_type,
            system_prompt=_system_prompt,
            retries=retries,
            deps_type=deps_type or GlobalState,
            tools=tools
        )
        
        # Add middleware for logging and timing
        self.use_middleware(LoggingMiddleware(logger))
        self.use_middleware(TimingMiddleware(logger))
        
        # Add a direct hook for error handling
        self.add_hook(HookPoint.ON_ERROR, self._handle_summary_error)
    
    async def _handle_summary_error(self, error: Exception, state: BaseModel, operation: str, **kwargs) -> Any:
        """Handle errors during summarization operations.
        
        Args:
            error: The exception that occurred.
            state: The state that was being processed.
            operation: The operation being performed when the error occurred.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The updated state with an error message.
        """
        logger.error(f"Summary error in {operation}: {error}")
        
        if isinstance(state, GlobalState):
            state.add_message("assistant", f"I encountered an error while summarizing: {str(error)}")
            return state
        
        # If we can't handle the error, let it propagate
        return error
    
    @hook(HookPoint.POST_RUN)
    async def log_summary_completion(self, state: GlobalState, result: GlobalState, **kwargs) -> GlobalState:
        """Log the completion of summarization.
        
        Args:
            state: The original state.
            result: The result state after running the agent.
            **kwargs: Additional keyword arguments.
            
        Returns:
            The result state.
        """
        logger.info(f"Summarization completed successfully")
        return result
    
    async def _run_implementation(self, state: GlobalState, **kwargs) -> GlobalState:
        """Implement the summary agent's run logic.
        
        Args:
            state: The current state of the conversation.
            **kwargs: Additional keyword arguments to pass to the agent.
            
        Returns:
            Updated state after the agent has processed it.
        """
        # Get the user's query
        text_to_summarize = state.get_latest_user_message()
        
        # Create a prompt for the agent
        prompt = f"""
        Please summarize the following text into key points:
        {text_to_summarize}
        
        Provide a concise summary with the main ideas and important details.
        """
        
        # Log the operation
        logger.info(f"Running summary agent with text: {text_to_summarize[:100]}...")
        
        # Execute the agent
        response = await self.agent.run(prompt, deps=state, message_history=state.chat_history, **kwargs)
        state.chat_history.extend(response.all_messages())
        
        # Process the response
        return await self._process_response_implementation(response, state)
    
    async def _process_response_implementation(self, response, state: GlobalState, **kwargs) -> GlobalState:
        """Process the agent response and update the state."""
        # Add the response to the state
        if hasattr(response, "content"):
            state.add_message("assistant", response.content)
        else:
            state.add_message("assistant", "I couldn't summarize that text.")
        
        return state

async def run_flexible_orchestrator(
    query: str,
    subagents: Dict[str, BaseAgent]
) -> GlobalState:
    """Run the flexible orchestrator agent with a user query and subagents.
    
    Args:
        query: The user query to process.
        subagents: Dictionary of subagents to use as tools.
        
    Returns:
        The final state after processing the query.
    """
    # Create a flexible orchestrator with the provided subagents
    orchestrator = FlexibleOrchestratorAgent(subagents=subagents)
    
    # Initialize state with the user query
    state = GlobalState()
    state.add_message("user", query)
    
    # Log the query
    logger.info(f"Processing query with flexible orchestrator: {query}")
    
    # Run the orchestrator agent
    try:
        # The orchestrator will call the appropriate subagents as needed
        result_state = await orchestrator.run(state)
        
        # Log the result
        if result_state.plan:
            logger.info(f"Generated plan with {len(result_state.plan)} steps")
            for i, step in enumerate(result_state.plan, 1):
                logger.info(f"Step {i}: {step}")
        
        # Return the final state
        return result_state
        
    except Exception as e:
        logger.error(f"Error running flexible orchestrator: {str(e)}")
        state.add_message("assistant", f"I encountered an error: {str(e)}")
        return state

async def main():
    """Run the example demonstrating the flexible orchestrator with different agents."""
    # Create different types of agents
    planner_agent = PlannerAgent(agent_name="task_planner")
    research_agent = ResearchAgent()
    summary_agent = SummaryAgent()
    
    # Example 1: Using planner agent only
    logger.info("\n" + "=" * 50)
    logger.info("Example 1: Using Planner Agent Only")
    logger.info("=" * 50)
    
    subagents = {"plan_task": planner_agent}
    query = "What are the steps to bake a chocolate cake?"
    
    result = await run_flexible_orchestrator(query, subagents)
    
    print("\nResult with Planner Agent:")
    for message in result.messages:
        if message["role"] == "assistant":
            print(f"Assistant: {message['content']}")
    
    if result.plan:
        print("\nPlan:")
        for i, step in enumerate(result.plan, 1):
            print(f"{i}. {step}")
    print()
    
    # Wait a bit between examples
    await asyncio.sleep(1)
    
    # Example 2: Using research agent only
    logger.info("\n" + "=" * 50)
    logger.info("Example 2: Using Research Agent Only")
    logger.info("=" * 50)
    
    subagents = {"research_topic": research_agent}
    query = "Tell me about the history of chocolate cake."
    
    result = await run_flexible_orchestrator(query, subagents)
    
    print("\nResult with Research Agent:")
    for message in result.messages:
        if message["role"] == "assistant":
            print(f"Assistant: {message['content']}")
    print()
    
    # Wait a bit between examples
    await asyncio.sleep(1)
    
    # Example 3: Using multiple agents
    logger.info("\n" + "=" * 50)
    logger.info("Example 3: Using Multiple Agents")
    logger.info("=" * 50)
    
    subagents = {
        "plan_task": planner_agent,
        "research_topic": research_agent,
        "summarize_text": summary_agent
    }
    query = "I need to bake a chocolate cake for a birthday party. Can you help me plan and provide some history about chocolate cake?"
    
    result = await run_flexible_orchestrator(query, subagents)
    
    print("\nResult with Multiple Agents:")
    for message in result.messages:
        if message["role"] == "assistant":
            print(f"Assistant: {message['content']}")
    
    if result.plan:
        print("\nPlan:")
        for i, step in enumerate(result.plan, 1):
            print(f"{i}. {step}")
    print()

if __name__ == "__main__":
    # Run the example
    asyncio.run(main())