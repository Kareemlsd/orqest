"""Example of using FlexibleOrchestratorAgent with different agents as tools.

This example demonstrates how to use the FlexibleOrchestratorAgent to orchestrate
different types of agents without hardcoded references to specific agent types.
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from examples.agents import GlobalState, PlannerAgent
from examples.agents.flexible_orchestrator import FlexibleOrchestratorAgent
from orqest.agents.base_agent import BaseAgent, NoValidResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ResearchAgent(BaseAgent[GlobalState]):
    """Example research agent that can find information on topics."""
    
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
    
    async def run(self, state: GlobalState, **kwargs) -> GlobalState:
        """Run the research agent to find information.
        
        Args:
            state: The current state of the conversation.
            **kwargs: Additional keyword arguments to pass to the agent.
            
        Returns:
            Updated state after the agent has processed it.
        """
        try:
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
            return await self._process_agent_response(response, state)
            
        except Exception as e:
            # Handle errors
            logger.error(f"Error running research agent: {str(e)}")
            state.add_message("assistant", f"I encountered an error while researching: {str(e)}")
            return state
    
    async def _process_agent_response(self, response, state: GlobalState, **kwargs) -> GlobalState:
        """Process the agent response and update the state."""
        # Add the response to the state
        if hasattr(response, "content"):
            state.add_message("assistant", response.content)
        else:
            state.add_message("assistant", "I couldn't find any information on that topic.")
        
        return state

class SummaryAgent(BaseAgent[GlobalState]):
    """Example summary agent that can summarize text."""
    
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
    
    async def run(self, state: GlobalState, **kwargs) -> GlobalState:
        """Run the summary agent to summarize text.
        
        Args:
            state: The current state of the conversation.
            **kwargs: Additional keyword arguments to pass to the agent.
            
        Returns:
            Updated state after the agent has processed it.
        """
        try:
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
            return await self._process_agent_response(response, state)
            
        except Exception as e:
            # Handle errors
            logger.error(f"Error running summary agent: {str(e)}")
            state.add_message("assistant", f"I encountered an error while summarizing: {str(e)}")
            return state
    
    async def _process_agent_response(self, response, state: GlobalState, **kwargs) -> GlobalState:
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