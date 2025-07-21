"""Test script for error handling in Orqest agents."""
import pytest
import logging
from unittest.mock import patch, MagicMock

from examples.agents import GlobalState, PlannerAgent, OrchestratorAgent
from orqest.agents.base_agent import NoValidResponse
from orqest.errors import (
    ErrorSeverity,
    ErrorCategory,
    ErrorContext,
    OrqestError,
    AgentError,
    LLMError,
    ValidationError,
    ToolError,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@pytest.fixture
def planner_agent():
    """Fixture that provides a PlannerAgent instance."""
    return PlannerAgent()


@pytest.fixture
def orchestrator_agent():
    """Fixture that provides an OrchestratorAgent instance."""
    return OrchestratorAgent()


@pytest.fixture
def global_state():
    """Fixture that provides a GlobalState instance with a user message."""
    state = GlobalState()
    state.add_message("user", "What are the steps to bake a chocolate cake?")
    return state


@pytest.mark.asyncio
async def test_planner_agent_error_handling(planner_agent, global_state):
    """Test error handling in the PlannerAgent."""
    logger.info("Testing PlannerAgent error handling...")
    
    # Mock the agent.run method to raise an exception
    with patch.object(planner_agent.agent, 'run', side_effect=Exception("Simulated LLM API error")):
        # Run the planner agent
        result_state = await planner_agent.run(global_state)
        
        # Verify that the result is a NoValidResponse
        assert isinstance(result_state, NoValidResponse)
        
        # Check that the error message is present
        assert result_state.error_message
        assert "Simulated LLM API error" in result_state.error_message
        
        logger.info("PlannerAgent error handling test completed successfully.")


@pytest.mark.asyncio
async def test_orchestrator_agent_error_handling(orchestrator_agent, global_state):
    """Test error handling in the OrchestratorAgent."""
    logger.info("Testing OrchestratorAgent error handling...")
    
    # Mock the agent.run method to raise an exception
    with patch.object(orchestrator_agent.agent, 'run', side_effect=Exception("Simulated LLM API error")):
        # Run the orchestrator agent
        result_state = await orchestrator_agent.run(global_state)
        
        # Verify that the result is a NoValidResponse
        assert isinstance(result_state, NoValidResponse)
        
        # Check that the error message is present
        assert result_state.error_message
        assert "Simulated LLM API error" in result_state.error_message
        
        logger.info("OrchestratorAgent error handling test completed successfully.")


@pytest.mark.asyncio
async def test_orchestrator_planner_tool_error_handling(orchestrator_agent, global_state):
    """Test error handling when the planner tool fails."""
    logger.info("Testing OrchestratorAgent-PlannerAgent tool error handling...")
    
    # Mock the planner agent's run method to raise an exception
    with patch.object(orchestrator_agent.planner_agent, 'run', side_effect=Exception("Simulated planner agent error")):
        # Run the orchestrator agent
        # This should trigger the _call_planner_agent method, which will catch the exception
        # and raise a ToolError, which should then be caught by the orchestrator's run method
        result_state = await orchestrator_agent.run(global_state)
        
        # Verify that the result is a NoValidResponse
        assert isinstance(result_state, NoValidResponse)
        
        # Check that the error message is present
        assert result_state.error_message
        assert "planner agent error" in result_state.error_message.lower() or "tool" in result_state.error_message.lower()
        
        logger.info("OrchestratorAgent-PlannerAgent tool error handling test completed successfully.")