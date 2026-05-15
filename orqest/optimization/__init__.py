"""Optimization primitives — reflective prompt evolution via GEPA.

The cognitive substrate's evolutionary layer. Orqest already produces every
signal a Pareto-optimizer needs (accuracy via output validation, confidence
via :class:`EnrichedOutput`, latency via :class:`Tracer.Span`, cost via
``pydantic_ai.usage.Usage``, robustness via :class:`HealingRunner`); this
battery wires GEPA (Genetic-Pareto reflective evolution, Agrawal et al.,
ICLR 2026 Oral) into that signal stream so the prompts driving your agents
evolve from real traces.

See :doc:`/concepts/optimization` for the full picture; this module hosts:

* :class:`OptimizationConfig` — frozen dataclass.
* :class:`MetricBundle` + :class:`MetricWeights` — per-example fitness.
* :class:`Genome` + :class:`PromptGene` / :class:`ScalarGene` /
  :class:`CategoricalGene` — what's evolvable.
* :class:`GoldExample` + :class:`Evaluator` — how to score a candidate.
* :class:`OrqestGEPAAdapter` + :class:`OrqestEvalBatch` — the GEPA bridge.
* :class:`OptimizationRunner` + :class:`OptimizationResult` — run the loop.
* :class:`OptimizationDiff` + :func:`apply_result` — write the winner back.

GEPA is an optional dependency. Install with::

    uv sync --group optimization
"""

from orqest.optimization.adapter import OrqestEvalBatch, OrqestGEPAAdapter
from orqest.optimization.apply import OptimizationDiff, apply_result
from orqest.optimization.bundle import MetricBundle, MetricWeights
from orqest.optimization.config import FrontierType, OptimizationConfig
from orqest.optimization.evaluator import Evaluator, GoldExample
from orqest.optimization.genome import (
    CategoricalGene,
    Gene,
    Genome,
    PromptGene,
    ScalarGene,
)
from orqest.optimization.runner import OptimizationResult, OptimizationRunner

__all__ = [
    "CategoricalGene",
    "Evaluator",
    "FrontierType",
    "Gene",
    "Genome",
    "GoldExample",
    "MetricBundle",
    "MetricWeights",
    "OptimizationConfig",
    "OptimizationDiff",
    "OptimizationResult",
    "OptimizationRunner",
    "OrqestEvalBatch",
    "OrqestGEPAAdapter",
    "PromptGene",
    "ScalarGene",
    "apply_result",
]
