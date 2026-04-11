"""Shared data types for the orchestration module.

Defines the error-handling strategy enum, per-step configuration, and the
event type emitted during pipeline execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class ErrorStrategy(Enum):
    """How to handle a step failure during pipeline execution."""

    STOP = "stop"
    SKIP = "skip"
    RETRY = "retry"


@dataclass(frozen=True)
class StepConfig:
    """Per-step configuration for pipeline execution.

    Controls the step's name, error-handling strategy, and retry limits.
    """

    name: str = ""
    on_error: ErrorStrategy = ErrorStrategy.STOP
    max_retries: int = 1


EventType = Literal[
    "pipeline_start",
    "step_start",
    "step_complete",
    "step_skip",
    "step_error",
    "pipeline_complete",
    "pipeline_error",
]


@dataclass(frozen=True)
class PipelineEvent:
    """Event emitted during pipeline execution for observability."""

    event_type: EventType
    pipeline_name: str
    step_name: str = ""
    step_index: int = -1
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)
    error: Exception | None = field(default=None, compare=False)
