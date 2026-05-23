"""ADAS topology evolution + GEPA prompt optimization on BIRD-dev.

This package exposes a primitive registry (agents + callables) and a
:class:`TopologyEvaluator` subclass that scores topology candidates by
execution accuracy against a sampled BIRD-dev minibatch. The whole flow
runs through Orqest's own batteries:

* :class:`orqest.optimization.meta_agent.MetaAgentSearch` evolves the
  topology composition.
* :class:`orqest.optimization.runner.OptimizationRunner` (GEPA) refines
  the per-agent prompts inside the winning topology.

No bespoke search loop, no hand-rolled mutation engine — pure dog-food.
"""

from orqest.benchmarks.bird.adas.state import SQLTaskState
from orqest.benchmarks.bird.adas.registry import (
    build_agent_registry,
    build_callable_registry,
)
from orqest.benchmarks.bird.adas.evaluator import (
    BIRDTopologyEvaluator,
    bird_gold_examples,
)
from orqest.benchmarks.bird.adas.seed import seed_topology

__all__ = [
    "BIRDTopologyEvaluator",
    "SQLTaskState",
    "bird_gold_examples",
    "build_agent_registry",
    "build_callable_registry",
    "seed_topology",
]
