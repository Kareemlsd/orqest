"""Tests for Step protocol, AgentStep, FunctionStep, and _coerce_step."""

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.orchestration.step import (
    AgentStep,
    FunctionStep,
    Step,
    _coerce_step,
)


# --- Helpers ---


class SimpleOutput(BaseModel):
    """Trivial output model for test agents."""

    text: str


class SimpleAgent(BaseAgent[BaseModel, SimpleOutput]):
    """Minimal concrete agent for testing."""

    async def _run_implementation(self, state, **kwargs):
        """Return the latest user message as structured output."""
        result = await self.call_model(
            state.get_latest_message("user") or "hello", state
        )
        return result.output


def _make_agent() -> SimpleAgent:
    """Build a SimpleAgent backed by TestModel."""
    return SimpleAgent(
        agent_name="test_agent",
        system_prompt="You are a test agent.",
        output_type=SimpleOutput,
        model=TestModel(),
    )


# --- Tests ---


@pytest.mark.asyncio
async def test_agent_step_wraps_base_agent():
    """AgentStep wraps BaseAgent, creates GlobalState, and returns output."""
    agent = _make_agent()
    step = AgentStep(agent)

    assert step.step_name == "test_agent"
    result = await step.execute("say hello")
    assert isinstance(result, SimpleOutput)


@pytest.mark.asyncio
async def test_agent_step_custom_prompt_builder():
    """AgentStep uses a custom prompt_builder when provided."""
    agent = _make_agent()
    calls: list[str] = []

    def custom_builder(data):
        """Record and transform input to a custom prompt."""
        calls.append(data)
        return f"CUSTOM: {data}"

    step = AgentStep(agent, prompt_builder=custom_builder)
    await step.execute("input_value")

    assert calls == ["input_value"]


@pytest.mark.asyncio
async def test_function_step_wraps_async_callable():
    """FunctionStep wraps an async function and calls it correctly."""

    async def double(x):
        """Double the input."""
        return x * 2

    step = FunctionStep(double)
    result = await step.execute(5)
    assert result == 10


def test_function_step_name_defaults_to_function_name():
    """FunctionStep infers step_name from the function's __name__."""

    async def my_transform(x):
        """Transform input."""
        return x

    step = FunctionStep(my_transform)
    assert step.step_name == "my_transform"


def test_coerce_step_handles_all_types():
    """_coerce_step handles Step, BaseAgent, Callable, and rejects invalid."""
    agent = _make_agent()

    # BaseAgent -> AgentStep
    step = _coerce_step(agent)
    assert isinstance(step, AgentStep)

    # Callable -> FunctionStep
    async def fn(x):
        """Identity function."""
        return x

    step = _coerce_step(fn)
    assert isinstance(step, FunctionStep)

    # Step passthrough
    existing = FunctionStep(fn)
    assert _coerce_step(existing) is existing

    # Invalid -> TypeError
    with pytest.raises(TypeError, match="Cannot coerce"):
        _coerce_step(42)  # type: ignore[arg-type]
