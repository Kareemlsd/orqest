"""Tests for the PlannerAgent class.

These tests verify the functionality of the PlannerAgent, including its ability
to analyze task complexity and generate plans. The tests use mock RunContext objects
to simulate the context that would be passed to the agent's tools in a real execution.
"""
import pytest
import logging
from unittest.mock import patch, MagicMock

from pydantic_ai import RunContext
from examples.agents import GlobalState, PlannerAgent
from orqest.agents.base_agent import NoValidResponse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@pytest.fixture
def planner_agent():
    """Fixture that provides a PlannerAgent instance."""
    return PlannerAgent()

@pytest.fixture
def global_state():
    """Fixture that provides a GlobalState instance with a user message."""
    state = GlobalState()
    state.add_message("user", "What are the steps to bake a chocolate cake?")
    return state

@pytest.mark.asyncio
async def test_planner_agent_initialization(planner_agent):
    """Test that the PlannerAgent initializes correctly."""
    assert planner_agent.agent_name == "planner_agent"
    assert planner_agent.system_prompt is not None
    assert planner_agent.retries == 2
    assert len(planner_agent.tools) == 1

@pytest.mark.asyncio
async def test_planner_agent_run_success(planner_agent, global_state):
    """Test that the PlannerAgent can run successfully."""
    # Create a mock response
    mock_response = MagicMock()
    mock_response.output = MagicMock()
    mock_response.output.plan = ["Step 1: Preheat oven", "Step 2: Mix ingredients"]
    mock_response.content = "Here's a plan for baking a cake"
    mock_response.all_messages.return_value = ["message1", "message2"]
    
    # Mock the agent.run method to return our mock response
    with patch.object(planner_agent.agent, 'run', return_value=mock_response):
        # Run the planner agent
        result_state = await planner_agent.run(global_state)
        
        # Verify the result
        assert result_state is not None
        assert not isinstance(result_state, NoValidResponse)
        assert len(result_state.plan) == 2
        assert "Step 1: Preheat oven" in result_state.plan
        assert len(result_state.messages) > 1  # Original message + response
        assert len(result_state.chat_history) == 2  # From mock_response.all_messages

@pytest.mark.asyncio
async def test_planner_agent_run_error(planner_agent, global_state):
    """Test that the PlannerAgent handles errors correctly."""
    # Mock the agent.run method to raise an exception
    with patch.object(planner_agent.agent, 'run', side_effect=Exception("Test error")):
        # Run the planner agent
        result_state = await planner_agent.run(global_state)
        
        # Verify the result is a NoValidResponse
        assert isinstance(result_state, NoValidResponse)
        assert result_state.error_message == "Test error"
        assert result_state.agent_name == "planner_agent"
        assert result_state.operation == "run"

@pytest.mark.asyncio
async def test_planner_agent_invalid_response(planner_agent, global_state):
    """Test that the PlannerAgent handles invalid responses correctly."""
    # Create a mock response with no output
    mock_response = MagicMock()
    mock_response.output = None
    mock_response.all_messages.return_value = ["message1", "message2"]
    
    # Mock the agent.run method to return our mock response
    with patch.object(planner_agent.agent, 'run', return_value=mock_response):
        # Run the planner agent
        result_state = await planner_agent.run(global_state)
        
        # Verify the result
        assert result_state is not None
        assert not isinstance(result_state, NoValidResponse)  # It should still return a GlobalState
        assert len(result_state.messages) > 1  # Original message + error message
        # The last message should be the error message
        assert "I couldn't generate a valid plan" in result_state.messages[-1]["content"]

@pytest.mark.asyncio
async def test_analyze_task_complexity(planner_agent):
    """Test the _analyze_task_complexity method."""
    # Create a mock RunContext with a GlobalState
    # This simulates the context that would be passed to the tool in a real execution
    # The deps attribute is set to a GlobalState instance, which is what the tool expects
    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = GlobalState()
    
    result = planner_agent._analyze_task_complexity(mock_ctx, "Test task")
    assert result is not None
    assert "complexity" in result
    assert result["complexity"] == "simple"