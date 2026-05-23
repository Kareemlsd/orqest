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
async def test_keep_best_returns_higher_scoring_earlier_iteration():
    """keep_best=True (default) returns the iteration with the best score
    when the final iteration regressed."""
    scores_by_call = [0.8, 0.3]  # iter 1 scores 0.8, iter 2 regresses to 0.3
    call_count = 0

    def eval_fn(output):
        nonlocal call_count
        score = scores_by_call[call_count]
        call_count += 1
        return EvalResult(passed=False, score=score)

    def updater(current, output, eval_result):
        # Different state per iter so outputs differ deterministically
        return current + 10

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=eval_fn,
        state_updater=updater,
        max_iterations=2,
        # keep_best=True is the default
    )
    result = await loop.run(0)
    # iter 1 input=0, output=1, score=0.8 (best)
    # iter 2 input=10, output=11, score=0.3 (regressed)
    assert result.exit_reason == "max_iterations"
    assert result.output == 1, "should return iter-1's output (higher score)"
    assert result.best_iteration == 1
    assert result.best_score == 0.8
    assert result.iterations == 2  # both iterations ran


@pytest.mark.asyncio
async def test_keep_best_off_returns_last_iteration_legacy_behavior():
    """Explicit keep_best=False restores last-iteration semantics for callers
    that depend on it."""
    scores_by_call = [0.8, 0.3]
    call_count = 0

    def eval_fn(output):
        nonlocal call_count
        score = scores_by_call[call_count]
        call_count += 1
        return EvalResult(passed=False, score=score)

    def updater(current, output, eval_result):
        return current + 10

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=eval_fn,
        state_updater=updater,
        max_iterations=2,
        keep_best=False,  # opt out
    )
    result = await loop.run(0)
    assert result.exit_reason == "max_iterations"
    assert result.output == 11, "should return iter-2's output (last) even though regressed"
    # best_iteration/best_score ARE populated as informational metadata even
    # when keep_best=False — the flag only controls which `output` is returned.
    # This lets callers diagnose regressions without committing to keep-best.
    assert result.best_iteration == 1
    assert result.best_score == 0.8


@pytest.mark.asyncio
async def test_keep_best_no_op_without_numeric_scores():
    """When the evaluator never returns a numeric score, keep_best can't help —
    returns the last iteration's output (legacy behavior is preserved)."""
    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=lambda x: EvalResult(passed=False),  # no score
        state_updater=lambda c, o, e: c + 1,
        max_iterations=3,
        keep_best=True,
    )
    result = await loop.run(0)
    assert result.exit_reason == "max_iterations"
    assert result.output == 3, "iter 3 input=2, output=3 — last iteration"
    assert result.best_iteration is None
    assert result.best_score is None


@pytest.mark.asyncio
async def test_keep_best_does_not_override_passed_exit():
    """A passing iteration is always returned, even if an earlier iteration
    had a higher score. `passed=True` is the explicit success bar."""
    scores_by_call = [(False, 0.9), (False, 0.5), (True, 0.4)]
    call_count = 0

    def eval_fn(output):
        nonlocal call_count
        passed, score = scores_by_call[call_count]
        call_count += 1
        return EvalResult(passed=passed, score=score)

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=eval_fn,
        state_updater=lambda c, o, e: c + 10,
        max_iterations=5,
        keep_best=True,
    )
    result = await loop.run(0)
    assert result.exit_reason == "passed"
    # iter 3 input=20, output=21
    assert result.output == 21
    # best_iteration is the passing iter even though iter 1 scored higher
    assert result.best_iteration == 3


@pytest.mark.asyncio
async def test_keep_best_tied_scores_prefer_latest():
    """When the latest score equals the best, prefer the latest iteration
    (no regression — no reason to walk back)."""
    scores_by_call = [0.7, 0.7, 0.7]
    call_count = 0

    def eval_fn(output):
        nonlocal call_count
        score = scores_by_call[call_count]
        call_count += 1
        return EvalResult(passed=False, score=score)

    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=eval_fn,
        state_updater=lambda c, o, e: c + 10,
        max_iterations=3,
        keep_best=True,
    )
    result = await loop.run(0)
    assert result.exit_reason == "max_iterations"
    # iter 3 input=20, output=21 — latest wins on tied score
    assert result.output == 21
    # best_iteration was first to record the (tied) best score
    assert result.best_iteration == 1
    assert result.best_score == 0.7


@pytest.mark.asyncio
async def test_loop_result_best_iteration_metadata_on_passed():
    """LoopResult exposes best_iteration/best_score even for `passed` exits."""
    loop = RefinementLoop(
        FunctionStep(_increment),
        evaluator=lambda x: EvalResult(passed=True, score=0.9),
        state_updater=_identity_updater,
    )
    result = await loop.run(0)
    assert result.exit_reason == "passed"
    assert result.best_iteration == 1
    assert result.best_score == 0.9


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
