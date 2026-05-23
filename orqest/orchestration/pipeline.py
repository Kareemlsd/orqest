"""Sequential pipeline that chains Steps with per-step error handling.

Pipeline accepts a list of StepLike values (or tuples with StepConfig),
coerces them to Steps, and runs them sequentially — feeding each step's
output as the next step's input.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Generic, TypeVar

from orqest.orchestration.step import Step, StepLike, _coerce_step
from orqest.orchestration.types import ErrorStrategy, PipelineEvent, StepConfig

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class PipelineStepError(Exception):
    """Raised when a step fails with ErrorStrategy.STOP."""

    def __init__(self, message: str, *, step_name: str, step_index: int) -> None:
        """Store the failing step's name and index alongside the message."""
        super().__init__(message)
        self.step_name = step_name
        self.step_index = step_index


class StepSkipped(Exception):
    """Internal signal that a step was skipped due to ErrorStrategy.SKIP."""

    def __init__(self, step_name: str) -> None:
        """Store the skipped step's name."""
        super().__init__(step_name)
        self.step_name = step_name


class Pipeline(Generic[InputT, OutputT]):
    """Run a sequence of steps, feeding each output into the next input.

    Each entry in *steps* is either a StepLike value or a (StepLike, StepConfig)
    tuple. StepLike values are auto-coerced via _coerce_step.
    """

    def __init__(
        self,
        steps: list[StepLike | tuple[StepLike, StepConfig]],
        *,
        name: str = "pipeline",
    ) -> None:
        """Validate and coerce the step list.

        Raises ValueError if *steps* is empty.
        """
        if not steps:
            raise ValueError("Pipeline requires at least one step")

        self.name = name
        self._steps: list[tuple[Step, StepConfig]] = []
        for entry in steps:
            if isinstance(entry, tuple):
                raw_step, config = entry
                step = _coerce_step(raw_step)
                self._steps.append((step, config))
            else:
                step = _coerce_step(entry)
                config = StepConfig(name=step.step_name)
                self._steps.append((step, config))

    async def run(self, input_data: InputT) -> OutputT:
        """Execute all steps sequentially, returning the final output."""
        data: Any = input_data
        async for event in self.run_stream(input_data):
            if event.event_type == "pipeline_error":
                raise event.error  # type: ignore[misc]
            if event.event_type == "pipeline_complete":
                data = event.data.get("output", data)
        return data  # type: ignore[return-value]

    async def run_stream(self, input_data: InputT) -> AsyncIterator[PipelineEvent]:
        """Execute steps and yield PipelineEvent at each lifecycle point."""
        yield PipelineEvent(
            event_type="pipeline_start",
            pipeline_name=self.name,
        )

        data: Any = input_data
        for index, (step, config) in enumerate(self._steps):
            step_name = config.name or step.step_name
            yield PipelineEvent(
                event_type="step_start",
                pipeline_name=self.name,
                step_name=step_name,
                step_index=index,
            )
            try:
                data = await self._execute_step(step, config, data, index)
                yield PipelineEvent(
                    event_type="step_complete",
                    pipeline_name=self.name,
                    step_name=step_name,
                    step_index=index,
                    data={"output": data},
                )
            except StepSkipped:
                yield PipelineEvent(
                    event_type="step_skip",
                    pipeline_name=self.name,
                    step_name=step_name,
                    step_index=index,
                )
            except PipelineStepError as exc:
                yield PipelineEvent(
                    event_type="pipeline_error",
                    pipeline_name=self.name,
                    step_name=step_name,
                    step_index=index,
                    error=exc,
                )
                raise

        yield PipelineEvent(
            event_type="pipeline_complete",
            pipeline_name=self.name,
            data={"output": data},
        )

    async def _execute_step(
        self,
        step: Step,
        config: StepConfig,
        input_data: Any,
        index: int,
    ) -> Any:
        """Execute a single step with the configured error strategy."""
        step_name = config.name or step.step_name
        if config.on_error is ErrorStrategy.RETRY:
            return await self._execute_with_retry(
                step, step_name, input_data, index, config.max_retries
            )
        try:
            return await step.execute(input_data)
        except Exception as exc:
            if config.on_error is ErrorStrategy.SKIP:
                raise StepSkipped(step_name) from exc
            raise PipelineStepError(
                str(exc), step_name=step_name, step_index=index
            ) from exc

    async def _execute_with_retry(
        self,
        step: Step,
        step_name: str,
        input_data: Any,
        index: int,
        max_retries: int,
    ) -> Any:
        """Retry the step up to *max_retries* times before raising."""
        last_exc: Exception | None = None
        for _ in range(max_retries + 1):
            try:
                return await step.execute(input_data)
            except Exception as exc:  # noqa: S110
                last_exc = exc
        raise PipelineStepError(
            str(last_exc), step_name=step_name, step_index=index
        ) from last_exc
