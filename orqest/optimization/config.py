"""Configuration for the optimization subsystem.

Frozen dataclass matching :class:`HealingConfig` and :class:`MetacognitionConfig`
patterns. Defaults are conservative — the optimizer only runs when explicitly
invoked via :class:`OptimizationRunner`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from orqest.optimization.bundle import MetricWeights

FrontierType = Literal["instance", "objective", "hybrid", "cartesian"]
"""GEPA's native Pareto-frontier shapes:

* ``"instance"`` — best candidate per validation example (the original GEPA paper)
* ``"objective"`` — best candidate per metric dimension (accuracy / cost / ...)
* ``"hybrid"`` — both, jointly. The recommended default for Orqest because the
  battery feeds GEPA both per-example scores and per-objective scores.
* ``"cartesian"`` — every (instance × objective) pair. Largest frontier; use only
  when search budget allows.
"""

_VALID_FRONTIER_TYPES: tuple[FrontierType, ...] = (
    "instance",
    "objective",
    "hybrid",
    "cartesian",
)


@dataclass(frozen=True)
class OptimizationConfig:
    """Knobs for the optimization battery.

    Pass explicitly to :class:`OptimizationRunner`.
    """

    max_metric_calls: int = 150
    """GEPA's rollout budget — total ``evaluate()`` calls across the search.
    150 is a reasonable default for a 10–20 example gold set; scale linearly
    with eval-set size if you want more iterations."""

    reflection_model: str | None = None
    """``provider:model_id`` for the LLM that proposes prompt mutations.
    ``None`` falls back to :attr:`OrqestConfig.llm_model`. **Use the strongest
    model you can afford here** — this is the optimizer's brain. The task
    model (whatever the user's ``agent_factory`` constructs the agent with)
    can stay cheap; the reflection model should not.

    Note: there is no ``task_model`` field. The model the candidate prompt
    runs against is whatever the user's ``agent_factory`` wires into the
    :class:`BaseAgent`; GEPA's adapter API explicitly forbids passing a
    ``task_lm`` when an adapter is supplied (the adapter owns it)."""

    minibatch_size: int = 3
    """Examples sampled per acceptance test. GEPA uses ``sum(scores)`` over
    the minibatch to decide whether a mutation beats its parent."""

    valset_fraction: float = 0.3
    """When :meth:`OptimizationRunner.optimize` receives no explicit valset,
    this fraction of ``trainset`` is held out (deterministically with
    :attr:`seed`) for Pareto tracking."""

    weights: MetricWeights = field(default_factory=MetricWeights)
    """Drives :meth:`MetricBundle.scalarize` — the per-example float that
    GEPA's acceptance test compares. The per-objective ``objective_scores``
    GEPA also receives are unweighted; weights only matter for the scalar
    summary and for which candidate ``best_candidate`` resolves to."""

    seed: int | None = 42
    """Random seed for trainset/valset splitting and any sampling. ``None``
    disables seeding (every run differs)."""

    dry_run_default: bool = True
    """Default value for :func:`apply_result(..., dry_run=...)`. When True,
    applying the result prints the diff but does not mutate the agent."""

    enable_scalar_genes: bool = False
    """Gate for :class:`ScalarGene` evolution (W1.1+). When False (default),
    :meth:`OptimizationRunner.optimize` raises ``NotImplementedError`` if a
    :class:`ScalarGene` appears in the genome."""

    enable_categorical_genes: bool = False
    """Gate for :class:`CategoricalGene` evolution (W1.1+). Same semantics as
    :attr:`enable_scalar_genes`."""

    cache_evaluations: bool = True
    """Pass-through to GEPA's built-in ``cache_evaluation`` knob —
    de-duplicates ``(candidate, example)`` evaluations during Pareto
    selection. 2–5× cost saving for free."""

    emit_per_example_events: bool = False
    """Off by default — 150 metric_calls × N examples can be 1000+ events
    per run, flooding the bus. When False, :class:`OrqestGEPAAdapter` only
    emits ``optimization.iteration_completed`` summaries."""

    frontier_type: FrontierType = "hybrid"
    """Pass-through to GEPA's ``optimize(frontier_type=...)``. Default
    ``"hybrid"`` because the battery feeds GEPA both ``scores`` (per-example
    scalar) and ``objective_scores`` (per-dimension); ``"hybrid"`` exploits
    both. See :data:`FrontierType` for alternatives."""

    def __post_init__(self) -> None:
        if self.max_metric_calls <= 0:
            raise ValueError("max_metric_calls must be > 0")
        if self.minibatch_size < 1:
            raise ValueError("minibatch_size must be >= 1")
        if not 0.0 < self.valset_fraction < 1.0:
            raise ValueError(
                "valset_fraction must be in the open interval (0, 1)"
            )
        if self.frontier_type not in _VALID_FRONTIER_TYPES:
            raise ValueError(
                f"frontier_type must be one of {_VALID_FRONTIER_TYPES}, "
                f"got {self.frontier_type!r}"
            )
