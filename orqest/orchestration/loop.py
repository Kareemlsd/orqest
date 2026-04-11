"""Refinement loop that iterates a step until an evaluator passes or limits hit.

Supports sync/async function evaluators and BaseAgent evaluators, with
configurable convergence detection, timeout, and max-iteration limits.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.orchestration.step import StepLike, _coerce_step

StateT = TypeVar("StateT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class EvalResult:
    """Outcome of evaluating a single iteration's output."""

    passed: bool
    feedback: str = ""
    score: float | None = None


@dataclass(frozen=True)
class IterationRecord:
    """Record of a single refinement iteration."""

    iteration: int
    eval_result: EvalResult
    duration_ms: float


@dataclass(frozen=True)
class LoopResult(Generic[OutputT]):
    """Final result of a RefinementLoop run."""

    output: OutputT
    iterations: int
    exit_reason: str
    history: list[IterationRecord] = field(default_factory=list)


Evaluator = Callable[..., Any] | BaseAgent
"""An evaluator can be a sync/async callable or a BaseAgent."""


class RefinementLoop(Generic[StateT, OutputT]):
    """Iterate a step with evaluation feedback until convergence or limits.

    The loop runs the step, evaluates the output, and uses the state_updater
    to produce the next input. It terminates when the evaluator passes, max
    iterations are reached, the timeout expires, or scores converge.
    """

    def __init__(
        self,
        step: StepLike,
        evaluator: Evaluator,
        *,
        state_updater: Callable[..., Any],
        max_iterations: int = 5,
        timeout: float | None = None,
        convergence_window: int | None = None,
        convergence_threshold: float = 0.01,
    ) -> None:
        """Configure the refinement loop.

        Args:
            step: The step to iterate.
            evaluator: Callable or BaseAgent that produces EvalResult.
            state_updater: (current_input, output, eval_result) -> next_input.
            max_iterations: Must be >= 1.
            timeout: Optional wall-clock timeout in seconds.
            convergence_window: Number of recent scores to check for convergence.
            convergence_threshold: Max score variance within the window.

        """
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")

        self._step = _coerce_step(step)
        self._evaluator = evaluator
        self._state_updater = state_updater
        self._max_iterations = max_iterations
        self._timeout = timeout
        self._convergence_window = convergence_window
        self._convergence_threshold = convergence_threshold

    async def run(self, initial_input: StateT) -> LoopResult[OutputT]:
        """Execute the refinement loop starting from *initial_input*."""
        current_input: Any = initial_input
        history: list[IterationRecord] = []
        scores: list[float] = []
        output: Any = None
        start = time.monotonic()

        for i in range(1, self._max_iterations + 1):
            if self._timeout is not None:
                elapsed = time.monotonic() - start
                if elapsed >= self._timeout:
                    return LoopResult(
                        output=output,
                        iterations=i - 1,
                        exit_reason="timeout",
                        history=history,
                    )

            iter_start = time.monotonic()
            output = await self._step.execute(current_input)
            eval_result = await self._call_evaluator(output)
            iter_ms = (time.monotonic() - iter_start) * 1000

            record = IterationRecord(
                iteration=i,
                eval_result=eval_result,
                duration_ms=iter_ms,
            )
            history.append(record)

            if eval_result.passed:
                return LoopResult(
                    output=output,
                    iterations=i,
                    exit_reason="passed",
                    history=history,
                )

            if eval_result.score is not None:
                scores.append(eval_result.score)

            if self._check_convergence(scores):
                return LoopResult(
                    output=output,
                    iterations=i,
                    exit_reason="converged",
                    history=history,
                )

            current_input = self._state_updater(current_input, output, eval_result)

        return LoopResult(
            output=output,
            iterations=self._max_iterations,
            exit_reason="max_iterations",
            history=history,
        )

    async def _call_evaluator(self, output: Any) -> EvalResult:
        """Invoke the evaluator, handling sync/async callables and BaseAgent."""
        if isinstance(self._evaluator, BaseAgent):
            state = GlobalState()
            state.add_message("user", str(output))
            return await self._evaluator.run(state)

        result = self._evaluator(output)
        if inspect.isawaitable(result):
            return await result
        return result

    def _check_convergence(self, scores: list[float]) -> bool:
        """Return True if recent scores have converged within the threshold."""
        if self._convergence_window is None:
            return False
        if len(scores) < self._convergence_window:
            return False
        window = scores[-self._convergence_window :]
        return (max(window) - min(window)) < self._convergence_threshold
