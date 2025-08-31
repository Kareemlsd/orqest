"""Tests for the Agent Lifecycle Hooks feature."""
import asyncio
import pytest
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from orqest.agents.base_agent import BaseAgent, NoValidResponse
from orqest.agents.hooks import HookPoint, Middleware, hook
from orqest.errors import ErrorSeverity


class TestState(BaseModel):
    """Test state for hook tests."""
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    results: List[str] = Field(default_factory=list)
    hook_calls: List[str] = Field(default_factory=list)


class TestAgent(BaseAgent[TestState]):
    """Test agent for hook tests."""
    
    def __init__(self):
        super().__init__(
            agent_name="test_agent",
            system_prompt="You are a test agent.",
            output_type=TestState,
            retries=1
        )
        
    async def _run_implementation(self, state: TestState, **kwargs) -> TestState:
        """Implement the agent's run logic."""
        state.results.append("run called")
        return state
        
    async def _process_response_implementation(
        self,
        response: Any,
        state: TestState,
        **kwargs
    ) -> TestState:
        """Implement the agent's response processing logic."""
        state.results.append("process_response called")
        return state


class TestMiddleware(Middleware):
    """Test middleware for hook tests."""
    
    async def pre_run(self, state: BaseModel, **kwargs) -> BaseModel:
        """Execute before the agent's run method is called."""
        if isinstance(state, TestState):
            state.hook_calls.append("middleware.pre_run")
        return state
    
    async def post_run(self, state: BaseModel, result: Any, **kwargs) -> Any:
        """Execute after the agent's run method is called."""
        if isinstance(result, TestState):
            result.hook_calls.append("middleware.post_run")
        return result
    
    async def pre_process_response(self, response: Any, state: BaseModel, **kwargs) -> tuple[Any, BaseModel]:
        """Execute before the agent's _process_agent_response method is called."""
        if isinstance(state, TestState):
            state.hook_calls.append("middleware.pre_process_response")
        return response, state
    
    async def post_process_response(self, response: Any, state: BaseModel, result: Any, **kwargs) -> Any:
        """Execute after the agent's _process_agent_response method is called."""
        if isinstance(result, TestState):
            result.hook_calls.append("middleware.post_process_response")
        return result
    
    async def on_error(self, error: Exception, state: BaseModel, operation: str, **kwargs) -> Any:
        """Execute when an error occurs during the agent's execution."""
        if isinstance(state, TestState):
            state.hook_calls.append(f"middleware.on_error.{operation}")
        return kwargs.get("response", None)


class TestAgentWithHooks(TestAgent):
    """Test agent with decorated hooks."""
    
    @hook(HookPoint.PRE_RUN)
    async def log_pre_run(self, state: TestState, **kwargs) -> TestState:
        """Log before the agent's run method is called."""
        state.hook_calls.append("decorated.pre_run")
        return state
    
    @hook(HookPoint.POST_RUN)
    async def log_post_run(self, state: TestState, result: TestState, **kwargs) -> TestState:
        """Log after the agent's run method is called."""
        result.hook_calls.append("decorated.post_run")
        return result


class ErrorAgent(BaseAgent[TestState]):
    """Test agent that raises errors."""
    
    def __init__(self):
        super().__init__(
            agent_name="error_agent",
            system_prompt="You are an error agent.",
            output_type=TestState,
            retries=1
        )
        
    async def _run_implementation(self, state: TestState, **kwargs) -> TestState:
        """Implement the agent's run logic."""
        raise ValueError("Test error in run")
        
    async def _process_response_implementation(
        self,
        response: Any,
        state: TestState,
        **kwargs
    ) -> TestState:
        """Implement the agent's response processing logic."""
        raise ValueError("Test error in process_response")
        return state


@pytest.mark.asyncio
async def test_hooks_execution():
    """Test that hooks are executed at the appropriate hook points."""
    # Create an agent and state
    agent = TestAgent()
    state = TestState()
    
    # Add hooks directly
    agent.add_hook(HookPoint.PRE_RUN, lambda s, **kw: s.hook_calls.append("direct.pre_run") or s)
    agent.add_hook(HookPoint.POST_RUN, lambda s, r, **kw: r.hook_calls.append("direct.post_run") or r)
    
    # Run the agent
    result = await agent.run(state)
    
    # Check that hooks were executed
    assert "direct.pre_run" in result.hook_calls
    assert "direct.post_run" in result.hook_calls
    assert "run called" in result.results


@pytest.mark.asyncio
async def test_middleware():
    """Test that middleware hooks are executed at the appropriate hook points."""
    # Create an agent and state
    agent = TestAgent()
    state = TestState()
    
    # Add middleware
    agent.use_middleware(TestMiddleware())
    
    # Run the agent
    result = await agent.run(state)
    
    # Process a response
    response = "test response"
    result = await agent._process_agent_response(response, result)
    
    # Check that middleware hooks were executed
    assert "middleware.pre_run" in result.hook_calls
    assert "middleware.post_run" in result.hook_calls
    assert "middleware.pre_process_response" in result.hook_calls
    assert "middleware.post_process_response" in result.hook_calls
    assert "run called" in result.results
    assert "process_response called" in result.results


@pytest.mark.asyncio
async def test_decorated_hooks():
    """Test that decorated hooks are executed at the appropriate hook points."""
    # Create an agent and state
    agent = TestAgentWithHooks()
    state = TestState()
    
    # Run the agent
    result = await agent.run(state)
    
    # Check that decorated hooks were executed
    assert "decorated.pre_run" in result.hook_calls
    assert "decorated.post_run" in result.hook_calls
    assert "run called" in result.results
