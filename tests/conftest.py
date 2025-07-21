"""Common test configuration and fixtures for Orqest tests."""
import sys
import pytest
import logging
import asyncio
from pathlib import Path

# Add the project root to the Python path to allow importing from examples
sys.path.append(str(Path(__file__).parent.parent))

from examples.agents import GlobalState, PlannerAgent, OrchestratorAgent

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Register the asyncio marker
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "asyncio: mark test as an asyncio test")

@pytest.fixture
def global_state():
    """Fixture that provides a GlobalState instance with a user message."""
    state = GlobalState()
    state.add_message("user", "What are the steps to bake a chocolate cake?")
    return state

@pytest.fixture
def planner_agent():
    """Fixture that provides a PlannerAgent instance."""
    return PlannerAgent()

@pytest.fixture
def orchestrator_agent():
    """Fixture that provides an OrchestratorAgent instance."""
    return OrchestratorAgent()