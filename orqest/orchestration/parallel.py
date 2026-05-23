"""Parallel execution of multiple steps.

Runs steps concurrently via asyncio tasks, collects results and errors,
and applies a merge strategy to successful outputs. Supports timeouts
and custom merge functions.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from orqest.orchestration.step import Step, _coerce_step

OutputT = TypeVar("OutputT")


class MergeStrategy:
    """Built-in merge strategies for combining parallel outputs."""

    @staticmethod
    def collect_all(results: list[Any]) -> list[Any]:
        """Return all successful results as a list (default strategy)."""
        return list(results)

    @staticmethod
    def first_wins(results: list[Any]) -> Any:
        """Return the first successful result, or None if empty."""
        return results[0] if results else None


@dataclass(frozen=True)
class ParallelResult(Generic[OutputT]):
    """Outcome of a parallel execution.

    Attributes:
        outputs: Per-step results; None for steps that failed or timed out.
        errors: Per-step exceptions; None for steps that succeeded.
        merged: Result of applying the merge strategy to successful outputs.

    """

    outputs: list[OutputT | None]
    errors: list[Exception | None]
    merged: Any


class Parallel(Generic[OutputT]):
    """Run multiple steps concurrently and merge their results.

    Each step is launched as an independent asyncio task. Timed-out tasks
    are cancelled and recorded as TimeoutError. The merge strategy receives
    only the successful (non-None) outputs.
    """

    def __init__(
        self,
        steps: list[Step | Any],
        *,
        merge: Callable[[list[Any]], Any] = MergeStrategy.collect_all,
        timeout: float | None = None,
        name: str = "parallel",
    ) -> None:
        """Initialize with steps, merge strategy, and optional timeout.

        Args:
            steps: StepLike objects to execute concurrently.
            merge: Callable that combines successful outputs into a final value.
            timeout: Maximum seconds to wait for all steps. None means no limit.
            name: Identifier for logging and events.

        Raises:
            ValueError: If steps is empty.

        """
        if not steps:
            raise ValueError("Parallel requires at least one step.")
        self._steps: list[Step] = [_coerce_step(s) for s in steps]
        self._merge = merge
        self._timeout = timeout
        self._name = name

    async def run(self, input_data: Any) -> ParallelResult[OutputT]:
        """Execute all steps concurrently and return aggregated results."""
        tasks = [
            asyncio.create_task(step.execute(input_data)) for step in self._steps
        ]

        outputs: list[OutputT | None] = [None] * len(tasks)
        errors: list[Exception | None] = [None] * len(tasks)

        done, pending = await asyncio.wait(
            tasks,
            timeout=self._timeout,
            return_when=asyncio.ALL_COMPLETED,
        )

        # Cancel and await pending (timed-out) tasks.
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending)

        for i, task in enumerate(tasks):
            if task in pending:
                errors[i] = TimeoutError(
                    f"Step '{self._steps[i].step_name}' timed out"
                )
            elif task.exception() is not None:
                errors[i] = task.exception()
            else:
                outputs[i] = task.result()

        successful = [o for o in outputs if o is not None]
        merged = self._merge(successful)

        return ParallelResult(outputs=outputs, errors=errors, merged=merged)
