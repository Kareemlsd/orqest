"""Test script for the orchestrator and planner agents."""
import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to the Python path to allow importing from orqest
sys.path.append(str(Path(__file__).parent.parent))

from test_examples.orchestrator_and_planner import (
    GlobalState,
    PlannerAgent,
    OrchestratorAgent,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_planner_agent():
    """Test the planner agent."""
    logger.info("Testing PlannerAgent...")
    
    # Initialize the planner agent
    planner = PlannerAgent()
    
    # Create a state with a user query
    state = GlobalState()
    state.add_message("user", "What are the steps to bake a chocolate cake?")
    
    # Run the planner agent
    try:
        result_state = await planner.run(state)
        logger.info(f"Planner agent plan: {result_state.plan}")
        logger.info("PlannerAgent test completed successfully.")
        return True
    except Exception as e:
        logger.error(f"Error testing PlannerAgent: {e}")
        return False

async def test_orchestrator_agent():
    """Test the orchestrator agent."""
    logger.info("Testing OrchestratorAgent...")
    
    # Initialize the orchestrator agent
    orchestrator = OrchestratorAgent()
    
    # Create a state with a user query
    state = GlobalState()
    state.add_message("user", "What are the steps to bake a chocolate cake?")
    
    # Run the orchestrator agent
    try:
        result_state = await orchestrator.run(state)
        logger.info(f"Orchestrator agent plan: {result_state.plan}")
        logger.info("OrchestratorAgent test completed successfully.")
        return True
    except Exception as e:
        logger.error(f"Error testing OrchestratorAgent: {e}")
        return False

async def main():
    """Run all tests."""
    logger.info("Starting tests...")
    
    # Test the planner agent
    planner_success = await test_planner_agent()
    
    # Test the orchestrator agent
    orchestrator_success = await test_orchestrator_agent()
    
    # Report results
    if planner_success and orchestrator_success:
        logger.info("All tests completed successfully!")
    else:
        logger.error("Some tests failed. Check the logs for details.")

if __name__ == "__main__":
    asyncio.run(main())