"""Tests for the OrchestratorAgent class.

These tests verify the functionality of the OrchestratorAgent, including its ability
to call the PlannerAgent as a tool. The tests use mock RunContext objects to simulate
the context that would be passed to the agent's tools in a real execution.
"""
import pytest
import logging
from unittest.mock import patch, MagicMock

from pydantic_ai import RunContext
from examples.agents import GlobalState, OrchestratorAgent, PlannerAgent
from orqest.agents.base_agent import NoValidResponse
from orqest.errors import ToolError, ErrorSeverity

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
async def test_orchestrator_agent_initialization(orchestrator_agent):
    """Test that the OrchestratorAgent initializes correctly."""
    assert orchestrator_agent.agent_name == "orchestrator"
    assert orchestrator_agent.system_prompt is not None
    assert orchestrator_agent.retries == 2
    assert len(orchestrator_agent.tools) == 1
    assert isinstance(orchestrator_agent.planner_agent, PlannerAgent)

@pytest.mark.asyncio
async def test_orchestrator_agent_run_success(orchestrator_agent, global_state):
    """Test that the OrchestratorAgent can run successfully."""
    # Create a mock response
    mock_response = MagicMock()
    mock_response.output = MagicMock()
    mock_response.output.plan = ["Step 1: Preheat oven", "Step 2: Mix ingredients"]
    mock_response.content = "Here's a plan for baking a cake"
    mock_response.all_messages.return_value = ["message1", "message2"]
    
    # Mock the agent.run method to return our mock response
    with patch.object(orchestrator_agent.agent, 'run', return_value=mock_response):
        # Run the orchestrator agent
        result_state = await orchestrator_agent.run(global_state)
        
        # Verify the result
        assert result_state is not None
        assert not isinstance(result_state, NoValidResponse)
        assert len(result_state.plan) == 2
        assert "Step 1: Preheat oven" in result_state.plan
        assert len(result_state.messages) > 1  # Original message + response
        assert len(result_state.chat_history) == 2  # From mock_response.all_messages

@pytest.mark.asyncio
async def test_orchestrator_agent_invalid_response(orchestrator_agent, global_state):
    """Test that the OrchestratorAgent handles invalid responses correctly."""
    # Create a mock response with no output
    mock_response = MagicMock()
    mock_response.output = None
    mock_response.all_messages.return_value = ["message1", "message2"]
    
    # Mock the agent.run method to return our mock response
    with patch.object(orchestrator_agent.agent, 'run', return_value=mock_response):
        # Run the orchestrator agent
        result_state = await orchestrator_agent.run(global_state)
        
        # Verify the result
        assert result_state is not None
        assert not isinstance(result_state, NoValidResponse)  # It should still return a GlobalState
        assert len(result_state.messages) > 1  # Original message + error message
        # The last message should be the error message
        assert "I couldn't process your request" in result_state.messages[-1]["content"]

@pytest.mark.asyncio
async def test_call_planner_agent_success(orchestrator_agent):
    """Test the _call_planner_agent method when successful."""
    # Create a mock result state
    mock_result_state = GlobalState()
    mock_result_state.plan = ["Step 1: Preheat oven", "Step 2: Mix ingredients"]
    
    # Create a mock RunContext with a GlobalState
    # This simulates the context that would be passed to the tool in a real execution
    # The deps attribute is set to a GlobalState instance, which is what the tool expects
    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = GlobalState()
    
    # Mock the planner_agent.run method to return our mock result state
    with patch.object(orchestrator_agent.planner_agent, 'run', return_value=mock_result_state):
        # Call the planner agent
        result = await orchestrator_agent._call_planner_agent(mock_ctx, "How do I bake a cake?")
        
        # Verify the result
        assert result is not None
        assert "plan" in result
        assert len(result["plan"]) == 2
        assert "Step 1: Preheat oven" in result["plan"]

@pytest.mark.asyncio
async def test_call_planner_agent_error(orchestrator_agent):
    """Test the _call_planner_agent method when the planner agent returns an error."""
    # Create a mock NoValidResponse
    mock_error_response = NoValidResponse(
        error_message="Planner agent error",
        error_type="TestError",
        agent_name="planner_agent",
        operation="run"
    )
    
    # Create a mock RunContext with a GlobalState
    # This simulates the context that would be passed to the tool in a real execution
    # The deps attribute is set to a GlobalState instance, which is what the tool expects
    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = GlobalState()
    
    # Mock the planner_agent.run method to return our mock error response
    with patch.object(orchestrator_agent.planner_agent, 'run', return_value=mock_error_response):
        # Call the planner agent and expect a ToolError
        with pytest.raises(ToolError) as excinfo:
            await orchestrator_agent._call_planner_agent(mock_ctx, "How do I bake a cake?")
        
        # Verify the error
        assert "Planner agent failed to generate a plan" in str(excinfo.value)
        assert excinfo.value.severity == ErrorSeverity.WARNING

@pytest.mark.asyncio
async def test_call_planner_agent_exception(orchestrator_agent):
    """Test the _call_planner_agent method when an exception occurs."""
    # Create a mock RunContext with a GlobalState
    # This simulates the context that would be passed to the tool in a real execution
    # The deps attribute is set to a GlobalState instance, which is what the tool expects
    mock_ctx = MagicMock(spec=RunContext)
    mock_ctx.deps = GlobalState()
    
    # Mock the planner_agent.run method to raise an exception
    with patch.object(orchestrator_agent.planner_agent, 'run', side_effect=Exception("Test error")):
        # Call the planner agent and expect a ToolError
        with pytest.raises(ToolError) as excinfo:
            await orchestrator_agent._call_planner_agent(mock_ctx, "How do I bake a cake?")
        
        # Verify the error
        assert "Error calling planner agent" in str(excinfo.value)
        assert excinfo.value.severity == ErrorSeverity.ERROR

@pytest.mark.asyncio
async def test_build_system_prompt(orchestrator_agent):
    """Test the _build_system_prompt method."""
    prompt = orchestrator_agent._build_system_prompt()
    assert prompt is not None
    assert "orchestrator agent" in prompt.lower()
    assert "planning and execution" in prompt.lower()