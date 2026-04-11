"""Tests for Pipeline execution, error handling, and event streaming."""

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.orchestration.pipeline import Pipeline, PipelineStepError
from orqest.orchestration.step import FunctionStep
from orqest.orchestration.types import ErrorStrategy, StepConfig


# --- Helpers ---


class SimpleOutput(BaseModel):
    """Trivial output model for test agents."""

    text: str


class SimpleAgent(BaseAgent[BaseModel, SimpleOutput]):
    """Minimal concrete agent for testing."""

    async def _run_implementation(self, state, **kwargs):
        """Return latest user message as structured output."""
        result = await self.call_model(
            state.get_latest_message("user") or "hello", state
        )
        return result.output


def _make_agent(name: str = "test_agent") -> SimpleAgent:
    """Build a SimpleAgent backed by TestModel."""
    return SimpleAgent(
        agent_name=name,
        system_prompt="You are a test agent.",
        output_type=SimpleOutput,
        model=TestModel(),
    )


async def _add_one(x):
    """Add one to the input."""
    return x + 1


async def _double(x):
    """Double the input."""
    return x * 2


# --- Tests ---


def test_empty_steps_raises():
    """Pipeline with empty step list raises ValueError."""
    with pytest.raises(ValueError, match="at least one step"):
        Pipeline([])


@pytest.mark.asyncio
async def test_single_step():
    """Single-step pipeline returns the step's output."""
    pipe = Pipeline([FunctionStep(_add_one)])
    result = await pipe.run(10)
    assert result == 11


@pytest.mark.asyncio
async def test_two_step_sequential():
    """Output of step 1 flows as input to step 2."""
    pipe = Pipeline([FunctionStep(_add_one), FunctionStep(_double)])
    result = await pipe.run(5)
    # (5 + 1) * 2 = 12
    assert result == 12


@pytest.mark.asyncio
async def test_pure_function_steps():
    """Pipeline of pure function steps transforms correctly."""

    async def upper(s):
        """Uppercase a string."""
        return s.upper()

    async def exclaim(s):
        """Add exclamation mark."""
        return s + "!"

    pipe = Pipeline([upper, exclaim])
    result = await pipe.run("hello")
    assert result == "HELLO!"


@pytest.mark.asyncio
async def test_mixed_agents_and_functions():
    """Pipeline mixes agent steps and function steps."""
    agent = _make_agent()

    async def extract_text(output):
        """Extract text from structured output."""
        return output.text

    pipe = Pipeline([agent, extract_text])
    result = await pipe.run("test input")
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_error_stop():
    """ErrorStrategy.STOP propagates PipelineStepError."""

    async def fail(x):
        """Always raise."""
        raise RuntimeError("boom")

    pipe = Pipeline([(fail, StepConfig(name="failing", on_error=ErrorStrategy.STOP))])

    with pytest.raises(PipelineStepError) as exc_info:
        await pipe.run("input")

    assert exc_info.value.step_name == "failing"
    assert exc_info.value.step_index == 0


@pytest.mark.asyncio
async def test_error_skip():
    """ErrorStrategy.SKIP passes input through on failure."""

    async def fail(x):
        """Always raise."""
        raise RuntimeError("boom")

    pipe = Pipeline([
        (fail, StepConfig(name="skippable", on_error=ErrorStrategy.SKIP)),
        FunctionStep(_add_one),
    ])

    result = await pipe.run(10)
    # fail is skipped, input 10 passes through, then +1 = 11
    assert result == 11


@pytest.mark.asyncio
async def test_error_retry_succeeds():
    """ErrorStrategy.RETRY succeeds on the second attempt."""
    call_count = 0

    async def flaky(x):
        """Fail on first call, succeed on second."""
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient")
        return x + 1

    pipe = Pipeline([
        (flaky, StepConfig(name="retryable", on_error=ErrorStrategy.RETRY, max_retries=1)),
    ])

    result = await pipe.run(5)
    assert result == 6
    assert call_count == 2


@pytest.mark.asyncio
async def test_error_retry_exhausted():
    """ErrorStrategy.RETRY raises PipelineStepError after max retries."""

    async def always_fail(x):
        """Always raise."""
        raise RuntimeError("permanent")

    pipe = Pipeline([
        (always_fail, StepConfig(name="doomed", on_error=ErrorStrategy.RETRY, max_retries=2)),
    ])

    with pytest.raises(PipelineStepError) as exc_info:
        await pipe.run("input")

    assert exc_info.value.step_name == "doomed"


@pytest.mark.asyncio
async def test_run_stream_events():
    """run_stream yields correct event sequence for a successful pipeline."""
    pipe = Pipeline([FunctionStep(_add_one)], name="test_pipe")

    events = []
    async for event in pipe.run_stream(1):
        events.append(event.event_type)

    assert events == [
        "pipeline_start",
        "step_start",
        "step_complete",
        "pipeline_complete",
    ]


@pytest.mark.asyncio
async def test_run_stream_error_event():
    """run_stream emits error event, then re-raises PipelineStepError."""

    async def fail(x):
        """Always raise."""
        raise RuntimeError("boom")

    pipe = Pipeline([(fail, StepConfig(name="bad", on_error=ErrorStrategy.STOP))])

    events = []
    with pytest.raises(PipelineStepError):
        async for event in pipe.run_stream("x"):
            events.append(event.event_type)

    assert "pipeline_error" in events


@pytest.mark.asyncio
async def test_type_coercion():
    """BaseAgent and callable are auto-wrapped when passed directly."""
    agent = _make_agent()

    async def to_str(output):
        """Convert to string."""
        return str(output)

    # Should not raise — coercion happens in __init__
    pipe = Pipeline([agent, to_str])
    assert len(pipe._steps) == 2  # noqa: SLF001
