"""Orchestration primitives for composing agents.

Provides Pipeline (sequential), Parallel (concurrent), Router (conditional),
and RefinementLoop (iterative) — plus the Step protocol for defining
executable units.
"""

from orqest.orchestration.loop import (
    EvalResult,
    Evaluator,
    IterationRecord,
    LoopResult,
    RefinementLoop,
)
from orqest.orchestration.parallel import MergeStrategy, Parallel, ParallelResult
from orqest.orchestration.pipeline import Pipeline, PipelineStepError
from orqest.orchestration.router import Route, Router, RouterError
from orqest.orchestration.step import AgentStep, FunctionStep, Step, StepLike
from orqest.orchestration.types import ErrorStrategy, PipelineEvent, StepConfig

__all__ = [
    "AgentStep",
    "ErrorStrategy",
    "EvalResult",
    "Evaluator",
    "FunctionStep",
    "IterationRecord",
    "LoopResult",
    "MergeStrategy",
    "Parallel",
    "ParallelResult",
    "Pipeline",
    "PipelineEvent",
    "PipelineStepError",
    "RefinementLoop",
    "Route",
    "Router",
    "RouterError",
    "Step",
    "StepConfig",
    "StepLike",
]
