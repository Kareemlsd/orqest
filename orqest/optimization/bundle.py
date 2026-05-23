"""Multi-objective fitness signals for optimization.

:class:`MetricBundle` aggregates the signals Orqest already produces
(accuracy via output validation, confidence via :class:`EnrichedOutput`,
latency via :class:`Tracer.Span`, cost via ``pydantic_ai.usage.Usage``,
robustness via healing-detector firings) into a typed payload that the
optimizer feeds to GEPA in two complementary forms:

* :meth:`MetricBundle.scalarize` produces the single per-example float GEPA
  uses for acceptance tests and ranking. Driven by :class:`MetricWeights`.
* :meth:`MetricBundle.to_per_instance_scores` produces the per-objective
  ``dict[str, float]`` GEPA stores in :class:`EvaluationBatch.objective_scores`,
  enabling the native multi-objective Pareto frontier (set
  ``frontier_type="hybrid"`` on :class:`OptimizationConfig`).

Cost and latency enter ``scalarize`` as raw quantities (USD, ms) multiplied
by negative weights; for ``to_per_instance_scores`` they are emitted unchanged
so GEPA can compare candidates on each axis independently.
"""

from __future__ import annotations

import statistics
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MetricWeights(BaseModel):
    """Weights for :meth:`MetricBundle.scalarize`.

    Negative weights penalize (cost, latency); positive weights reward
    (accuracy, confidence, robustness). Defaults are calibrated for
    "accuracy is king, but don't ignore cost / latency / calibration"
    against realistic LLM call latencies (1–10 seconds = 1k–10k ms) and
    realistic per-call costs ($0.0001 – $0.05).

    Magnitude rationale: a perfect-accuracy candidate at ~5 s / $0.005
    scores ``≈ 1.0 + 0 + 0 - 0.05 - 0.05 = 0.9``. Latency and cost act
    as soft tiebreakers; accuracy stays the dominant axis. If you care
    more about cost, override; production users will tune these per app.
    """

    model_config = ConfigDict(frozen=True)

    accuracy: float = 1.0
    confidence: float = 0.1
    cost_usd: float = -10.0
    """``-10.0`` per USD: a $0.001 call is ``-0.01``, $0.01 is ``-0.10``,
    $0.10 is ``-1.0``. Calibrated so per-call cost is a soft tiebreaker
    against accuracy (range 0–1), not a dominant signal."""
    latency_ms: float = -0.00002
    """``-0.00002`` per ms: a 1 s call is ``-0.02``, a 5 s call is
    ``-0.10``, a 30 s call is ``-0.60``. Same logic as ``cost_usd`` —
    soft tiebreaker, not dominant."""
    robustness: float = 0.2


class MetricBundle(BaseModel):
    """One example's multi-dimensional fitness.

    Accuracy / confidence / robustness are normalized to ``[0, 1]``
    (higher is better). Cost (USD) and latency (ms) are raw, non-negative
    quantities (lower is better) — :class:`MetricWeights` carries negative
    weights so :meth:`scalarize` produces the right gradient.
    """

    model_config = ConfigDict(frozen=True)

    accuracy: float = Field(ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    robustness: float | None = Field(default=None, ge=0.0, le=1.0)

    raw: dict[str, Any] = Field(default_factory=dict)
    """Extension point — consumer-defined extras (e.g., per-tool counters).
    Surfaced in events / notebooks but ignored by :meth:`scalarize`."""

    n_trials: int = Field(default=1, ge=1)
    """Number of independent observations aggregated into this bundle.
    ``1`` (the default) means a single observation. Values ``> 1`` indicate
    this bundle is the *mean* of ``n_trials`` underlying bundles, produced
    by :meth:`MetricBundle.aggregate`. Use this when you've re-run the same
    candidate / example multiple times to wash out LLM run-to-run variance —
    the discovery from the coding benchmark was that single-trial numbers
    swing ±10pp on weaker models, so multi-trial averaging is often the
    right default for evaluator pipelines."""

    stdev: dict[str, float] | None = Field(default=None)
    """Per-dimension standard deviation across the trials this bundle
    aggregates. Keys mirror the metric field names (``accuracy``,
    ``confidence``, ``cost_usd``, ``latency_ms``, ``robustness``). ``None``
    when ``n_trials == 1`` (no dispersion to report). When a dimension was
    ``None`` in some trials but present in others, the stdev is computed
    only over trials where it was present — and omitted entirely from
    ``stdev`` when fewer than 2 such trials exist (single observations
    have no defined standard deviation)."""

    def scalarize(self, w: MetricWeights) -> float:
        """Single per-example fitness score for GEPA's acceptance test.

        Optional dimensions (``confidence``, ``robustness``) are skipped
        when ``None`` rather than treated as zero — a missing signal must
        not penalize a candidate that simply didn't surface it.
        """
        score = self.accuracy * w.accuracy
        score += self.cost_usd * w.cost_usd
        score += self.latency_ms * w.latency_ms
        if self.confidence is not None:
            score += self.confidence * w.confidence
        if self.robustness is not None:
            score += self.robustness * w.robustness
        return score

    def to_per_instance_scores(self, w: MetricWeights) -> dict[str, float]:
        """Per-dimension scores for GEPA's ``objective_scores`` field.

        Each key becomes an axis on GEPA's objective Pareto front when
        ``frontier_type`` is ``"objective"`` / ``"hybrid"`` / ``"cartesian"``.
        Optional dimensions that are ``None`` are omitted (not zero-filled)
        so the frontier doesn't conflate "absent" with "bad."
        """
        scores: dict[str, float] = {
            "accuracy": self.accuracy,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
        }
        if self.confidence is not None:
            scores["confidence"] = self.confidence
        if self.robustness is not None:
            scores["robustness"] = self.robustness
        return scores

    @classmethod
    def aggregate(cls, bundles: list[MetricBundle]) -> MetricBundle:
        """Mean each metric across ``bundles``; compute per-dimension stdev.

        Use this to collapse N independent observations of the same
        candidate / example into a single representative bundle. The
        returned bundle has ``n_trials = len(bundles)`` and a populated
        ``stdev`` dict (when N >= 2) so consumers can see dispersion
        alongside the central tendency.

        Optional dimensions (``confidence``, ``robustness``) are handled
        gracefully:

        * If *every* bundle has it ``None``, the aggregate also reports
          ``None`` for that dimension and omits it from ``stdev``.
        * If *some* bundles have it set and others ``None``, the aggregate
          reports the mean over present values. ``stdev`` includes the
          dimension only when 2 or more bundles supplied it.

        The ``raw`` dict of the first bundle is preserved as a
        representative sample (it's a consumer-defined extension point;
        merging semantics belong to the consumer, not this aggregator).

        Args:
            bundles: At least one bundle. Empty list raises ``ValueError``.

        Returns:
            A new ``MetricBundle`` with mean metrics + populated ``stdev``.

        Raises:
            ValueError: When ``bundles`` is empty.
        """
        if not bundles:
            raise ValueError(
                "MetricBundle.aggregate requires at least one bundle "
                "(got empty list); nothing to average."
            )
        if len(bundles) == 1:
            # Single observation: return unchanged (n_trials=1, stdev=None).
            # Callers can rely on aggregate([x]) == x for any x.
            return bundles[0]

        n = len(bundles)
        accuracy_mean = statistics.fmean(b.accuracy for b in bundles)
        cost_mean = statistics.fmean(b.cost_usd for b in bundles)
        latency_mean = statistics.fmean(b.latency_ms for b in bundles)

        # Optional dims: average over PRESENT values only
        confidence_vals = [b.confidence for b in bundles if b.confidence is not None]
        robustness_vals = [b.robustness for b in bundles if b.robustness is not None]
        confidence_mean = statistics.fmean(confidence_vals) if confidence_vals else None
        robustness_mean = statistics.fmean(robustness_vals) if robustness_vals else None

        # stdev requires >= 2 samples per dimension
        stdev: dict[str, float] = {
            "accuracy": statistics.stdev(b.accuracy for b in bundles),
            "cost_usd": statistics.stdev(b.cost_usd for b in bundles),
            "latency_ms": statistics.stdev(b.latency_ms for b in bundles),
        }
        if len(confidence_vals) >= 2:
            stdev["confidence"] = statistics.stdev(confidence_vals)
        if len(robustness_vals) >= 2:
            stdev["robustness"] = statistics.stdev(robustness_vals)

        return cls(
            accuracy=accuracy_mean,
            confidence=confidence_mean,
            cost_usd=cost_mean,
            latency_ms=latency_mean,
            robustness=robustness_mean,
            raw=dict(bundles[0].raw),  # representative; consumer owns merge semantics
            n_trials=n,
            stdev=stdev,
        )
