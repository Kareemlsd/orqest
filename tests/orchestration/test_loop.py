"""Tests for RefinementLoop with various evaluators, convergence, and timeout."""

import asyncio

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.orchestration.loop import EvalResult, RefinementLoop
from orqest.orchestration.step import FunctionStep


# --- Helpers ---


class SimpleOutput(BaseModel):
    """Trivial output model for evaluator agents."""

    text: str


class EvalAgent(BaseAgent[BaseModel, EvalResult]):
    """Agent that always passes evaluation."""

    async def _run_implementation(self, state, **kwargs):
        """Return a passing EvalResult."""
        result = await self.call_model(
            state.get_latest_message("user") or "evaluate", state
        )
        return EvalResult(passed=True, feedback="ok")


def _identity_updater(current, output, eval_result):
    """Return current input unchanged."""
    return current


async def _increment(x):
    """Add one to the input."""
    return x + 1


# --- Tests ---


def test_max_iterations_less_than_one():
    """max_iterations < 1 raises ValueError."""

    async def noop(x):
        """No-op step."""
        return x

    with pytest.raises(ValueError, match="max_iterations must be >= 1"):
        RefinementLoop(
            noop,
            evaluator=lambda x: EvalResult(passed=True),
            state_updater=_identity_updater,
            max_iterations=0,
        )


@pytest.mark.asyncio
async def test_passes_first_iteration():
    """Loop exits with 'passed' on first iteration when evaluator passes."""
    step = FunctionStep(_increment)
    loop = RefinementLoop(
        step,
        evaluator=lambda x: EvalResult(passed=True, feedback="good"),
        state_updater=_identity_updater,
    )
    result = await loop.run(0)
    assert result.iterations == 1
    assert result.exit_reason == "passed"
    assert result.output == 1


@pytest.mark.asyncio
async def test_passes_after_n_iterations():
    """Loop passes after a specific number of iterations."""
    call_count = 0

    def eval_fn(output):
        """Pass on the third call."""
        nonlocal call_count
        call_count += 1
        return EvalResult(passed=(call_count >= 3), feedback=f"attempt {call_count}")

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=eval_fn,
        state_updater=_identity_updater,
        max_iterations=5,
    )
    result = await loop.run(0)
    assert result.iterations == 3
    assert result.exit_reason == "passed"


@pytest.mark.asyncio
async def test_max_iterations_reached():
    """Loop exits with 'max_iterations' when evaluator never passes."""
    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=lambda x: EvalResult(passed=False, feedback="nope"),
        state_updater=_identity_updater,
        max_iterations=3,
    )
    result = await loop.run(0)
    assert result.iterations == 3
    assert result.exit_reason == "max_iterations"


@pytest.mark.asyncio
async def test_state_evolution():
    """state_updater transforms input between iterations."""
    values: list[int] = []

    async def capture_and_return(x):
        """Record the input and return it."""
        values.append(x)
        return x

    def increment_updater(current, output, eval_result):
        """Increment the state by 1 each iteration."""
        return current + 1

    loop = RefinementLoop(
        FunctionStep(capture_and_return),
        evaluator=lambda x: EvalResult(passed=False),
        state_updater=increment_updater,
        max_iterations=3,
    )
    await loop.run(0)
    assert values == [0, 1, 2]


@pytest.mark.asyncio
async def test_convergence_detection():
    """Loop exits with 'converged' when scores plateau."""
    call_count = 0

    def eval_fn(output):
        """Return declining scores that converge."""
        nonlocal call_count
        call_count += 1
        # Scores: 1.0, 1.0, 1.0 — within threshold
        return EvalResult(passed=False, score=1.0)

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=eval_fn,
        state_updater=_identity_updater,
        max_iterations=10,
        convergence_window=3,
        convergence_threshold=0.01,
    )
    result = await loop.run(0)
    assert result.exit_reason == "converged"
    assert result.iterations == 3


@pytest.mark.asyncio
async def test_timeout_exit():
    """Loop exits with 'timeout' when wall-clock time exceeds limit."""

    async def slow_step(x):
        """Sleep to simulate slow work."""
        await asyncio.sleep(0.05)
        return x

    loop = RefinementLoop(
        FunctionStep(slow_step),
        evaluator=lambda x: EvalResult(passed=False),
        state_updater=_identity_updater,
        max_iterations=100,
        timeout=0.01,
    )
    result = await loop.run(0)
    # Timeout checked at start of each iteration; first iteration runs,
    # then timeout triggers before the second.
    assert result.exit_reason == "timeout"


@pytest.mark.asyncio
async def test_agent_evaluator():
    """BaseAgent can serve as an evaluator."""
    eval_agent = EvalAgent(
        agent_name="eval",
        system_prompt="Evaluate output.",
        output_type=EvalResult,
        model=TestModel(),
    )

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=eval_agent,
        state_updater=_identity_updater,
        max_iterations=5,
    )
    result = await loop.run(0)
    assert result.exit_reason == "passed"
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_sync_function_evaluator():
    """A plain sync function works as an evaluator."""
    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=lambda x: EvalResult(passed=True),
        state_updater=_identity_updater,
    )
    result = await loop.run(0)
    assert result.exit_reason == "passed"


@pytest.mark.asyncio
async def test_async_function_evaluator():
    """An async function works as an evaluator."""

    async def async_eval(output):
        """Async evaluator that always passes."""
        return EvalResult(passed=True, feedback="async ok")

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=async_eval,
        state_updater=_identity_updater,
    )
    result = await loop.run(0)
    assert result.exit_reason == "passed"


@pytest.mark.asyncio
async def test_iteration_history_recorded():
    """Each iteration is recorded in result.history with correct data."""
    call_count = 0

    def eval_fn(output):
        """Pass on second call, with scores."""
        nonlocal call_count
        call_count += 1
        return EvalResult(
            passed=(call_count >= 2),
            feedback=f"iter {call_count}",
            score=float(call_count),
        )

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=eval_fn,
        state_updater=_identity_updater,
        max_iterations=5,
    )
    result = await loop.run(0)
    assert result.iterations == 2
    assert len(result.history) == 2
    assert result.history[0].iteration == 1
    assert result.history[0].eval_result.feedback == "iter 1"
    assert result.history[1].eval_result.passed is True
    assert result.history[1].duration_ms > 0
