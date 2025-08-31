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
