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
    """Final result of a RefinementLoop run.

    ``output`` is the iteration that the loop is returning to the caller. With
    ``keep_best=True`` (the default), this may be an *earlier* iteration's
    output than the final one — specifically the iteration that achieved the
    highest scored :class:`EvalResult`. ``best_iteration`` and ``best_score``
    record which iteration was kept and at what score; both are ``None`` when
    no iteration produced a numeric score.
    """

    output: OutputT
    iterations: int
    exit_reason: str
    history: list[IterationRecord] = field(default_factory=list)
    best_iteration: int | None = None
    best_score: float | None = None


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
        confidence_threshold: float | None = None,
        agent_self_eval: BaseAgent | None = None,
        keep_best: bool = True,
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
            confidence_threshold: When set AND ``EvalResult.score`` reaches
                this value, the loop exits with ``exit_reason="confident"``.
                Pairs naturally with ``agent_self_eval``.
            agent_self_eval: Optional :class:`BaseAgent` whose
                ``run_enriched`` is used to produce the per-iteration
                score (the agent's *own* confidence). When set,
                ``confidence_threshold`` is required. Takes precedence
                over ``evaluator`` for scoring: ``evaluator`` is still a
                required positional argument (so callers explicitly
                acknowledge the loop has a "fail by default" path), but
                it is *not invoked* while ``agent_self_eval`` is active.
                A synthetic ``EvalResult(passed=False,
                score=enriched.confidence)`` is produced each iteration,
                so the loop only exits early via ``confidence_threshold``
                — never via the implicit ``passed=True`` short-circuit.
            keep_best: When ``True`` (the default), track the iteration with
                the highest :attr:`EvalResult.score` and return THAT
                iteration's output if the final iteration regressed. Protects
                self-improving loops from "fixer breaks code that already
                worked" failure modes on imperfect models. The ``passed=True``
                early exit always wins over keep-best (a passing iteration is
                the explicit success bar). When the evaluator never returns a
                numeric ``score``, keep-best is a no-op and the legacy
                "return latest output" behavior holds. Set ``keep_best=False``
                to restore strict last-iteration semantics.

        """
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if agent_self_eval is not None and confidence_threshold is None:
            raise ValueError(
                "agent_self_eval requires confidence_threshold to be set; "
                "self-eval scores are meaningless without a passing bar."
            )
        if (
            agent_self_eval is not None
            and getattr(agent_self_eval, "confidence_protocol", None) is None
        ):
            raise ValueError(
                "agent_self_eval requires the agent to be constructed with a "
                "confidence_protocol; without one run_enriched yields "
                "confidence=None and the loop can never exit via 'confident'."
            )

        self._step = _coerce_step(step)
        self._evaluator = evaluator
        self._state_updater = state_updater
        self._max_iterations = max_iterations
        self._timeout = timeout
        self._convergence_window = convergence_window
        self._convergence_threshold = convergence_threshold
        self._confidence_threshold = confidence_threshold
        self._agent_self_eval = agent_self_eval
        self._keep_best = keep_best

    async def run(self, initial_input: StateT) -> LoopResult[OutputT]:
        """Execute the refinement loop starting from *initial_input*.

        With ``keep_best=True`` (the default), tracks the highest-scoring
        iteration and returns *its* output on any non-``passed`` exit if the
        final iteration regressed. The ``passed=True`` early exit always
        returns the passing iteration's output regardless of score.
        """
        current_input: Any = initial_input
        history: list[IterationRecord] = []
        scores: list[float] = []
        output: Any = None
        start = time.monotonic()

        # Best-so-far tracking (only meaningful when keep_best=True and the
        # evaluator returns numeric scores). Always populated when a score
        # is seen so LoopResult.best_iteration/best_score are accurate.
        best_output: Any = None
        best_score: float | None = None
        best_iteration: int | None = None
        last_eval_score: float | None = None

        for i in range(1, self._max_iterations + 1):
            if self._timeout is not None:
                elapsed = time.monotonic() - start
                if elapsed >= self._timeout:
                    chosen, chosen_iter = self._resolve_kept_output(
                        latest_output=output,
                        latest_score=last_eval_score,
                        latest_iter=i - 1,
                        best_output=best_output,
                        best_score=best_score,
                        best_iteration=best_iteration,
                    )
                    return LoopResult(
                        output=chosen,
                        iterations=i - 1,
                        exit_reason="timeout",
                        history=history,
                        best_iteration=best_iteration,
                        best_score=best_score,
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
            last_eval_score = eval_result.score

            # Track best-so-far on STRICT improvement (ties keep the earlier
            # one in best_score memory; the resolver still prefers the latest
            # on tied final score so we don't gratuitously walk back).
            if eval_result.score is not None and (
                best_score is None or eval_result.score > best_score
            ):
                best_output = output
                best_score = eval_result.score
                best_iteration = i

            if eval_result.passed:
                # passed is the explicit success bar — keep_best does NOT
                # override it. Also clears best_iteration/score to reflect
                # that the returned output is the passing iteration's.
                return LoopResult(
                    output=output,
                    iterations=i,
                    exit_reason="passed",
                    history=history,
                    best_iteration=i,
                    best_score=eval_result.score,
                )

            if eval_result.score is not None:
                scores.append(eval_result.score)

            # Confidence-driven exit: agent self-rated above the bar.
            if (
                self._confidence_threshold is not None
                and eval_result.score is not None
                and eval_result.score >= self._confidence_threshold
            ):
                return LoopResult(
                    output=output,
                    iterations=i,
                    exit_reason="confident",
                    history=history,
                    best_iteration=i,
                    best_score=eval_result.score,
                )

            if self._check_convergence(scores):
                chosen, chosen_iter = self._resolve_kept_output(
                    latest_output=output,
                    latest_score=eval_result.score,
                    latest_iter=i,
                    best_output=best_output,
                    best_score=best_score,
                    best_iteration=best_iteration,
                )
                return LoopResult(
                    output=chosen,
                    iterations=i,
                    exit_reason="converged",
                    history=history,
                    best_iteration=best_iteration,
                    best_score=best_score,
                )

            current_input = self._state_updater(current_input, output, eval_result)

        chosen, chosen_iter = self._resolve_kept_output(
            latest_output=output,
            latest_score=last_eval_score,
            latest_iter=self._max_iterations,
            best_output=best_output,
            best_score=best_score,
            best_iteration=best_iteration,
        )
        return LoopResult(
            output=chosen,
            iterations=self._max_iterations,
            exit_reason="max_iterations",
            history=history,
            best_iteration=best_iteration,
            best_score=best_score,
        )

    def _resolve_kept_output(
        self,
        *,
        latest_output: Any,
        latest_score: float | None,
        latest_iter: int,
        best_output: Any,
        best_score: float | None,
        best_iteration: int | None,
    ) -> tuple[Any, int]:
        """Decide which iteration's output to surface on non-``passed`` exit.

        - When ``keep_best=False`` → always the latest iteration's output.
        - When no iteration produced a score → latest (we have nothing to
          compare against).
        - When the latest score is None but we have a best → return the best
          (a known-scored candidate beats an unscored one).
        - When the latest score is *strictly less* than the best → return the
          best (regression protection).
        - Otherwise (latest >= best) → return latest (ties prefer freshness).
        """
        if not self._keep_best or best_output is None:
            return latest_output, latest_iter
        if latest_score is None:
            return best_output, best_iteration  # type: ignore[return-value]
        if best_score is not None and latest_score < best_score:
            return best_output, best_iteration  # type: ignore[return-value]
        return latest_output, latest_iter

    async def _call_evaluator(self, output: Any) -> EvalResult:
        """Invoke the evaluator, handling sync/async callables and BaseAgent.

        When ``agent_self_eval`` is configured, it takes precedence: the
        agent runs with ``run_enriched`` against the current output, and
        we synthesise an :class:`EvalResult` whose score is the agent's
        own confidence. ``passed=False`` so the loop only exits via
        ``confidence_threshold`` (the explicit metacognitive bar) rather
        than the implicit ``passed`` short-circuit.
        """
        if self._agent_self_eval is not None:
            state = GlobalState()
            state.add_message("user", str(output))
            enriched = await self._agent_self_eval.run_enriched(state)
            score = enriched.confidence
            feedback = ", ".join(enriched.uncertainty_targets)
            return EvalResult(passed=False, feedback=feedback, score=score)

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
