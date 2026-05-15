"""Bridge between GEPA's :class:`GEPAAdapter` Protocol and Orqest primitives.

GEPA owns the optimization loop (sampling, mutation, validation, Pareto
selection); the adapter is the only Orqest-aware code GEPA sees. Three
responsibilities, mirroring the upstream Protocol:

1. **`evaluate`** — run a candidate on a batch of examples, return scores
   (per-example scalar) and ``objective_scores`` (per-example dict so GEPA's
   ``frontier_type="hybrid"`` can compute multi-dimensional Pareto).
2. **`make_reflective_dataset`** — turn the evaluation results into a small
   JSON-serializable dataset the reflection LLM uses to propose better
   prompt text. Per-component, with each record describing inputs, outputs,
   confidence/uncertainty signals, and per-bundle dimension breakdown.
3. **Async bridging** — GEPA's interface is sync; Orqest is async. The
   adapter detects an already-running event loop (Jupyter) vs a fresh
   process (CLI / pytest) and dispatches accordingly.

Errors during per-example evaluation are *never* raised — the Protocol
explicitly requires a 0.0 fallback score with the failure captured in the
trajectory. :class:`Evaluator` already enforces this; the adapter just
forwards the result.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, ClassVar

from loguru import logger

from orqest.observability.events import AgentEvent, EventBus
from orqest.optimization._compat import EvaluationBatch
from orqest.optimization.bundle import MetricBundle, MetricWeights
from orqest.optimization.evaluator import Evaluator, GoldExample
from orqest.optimization.genome import Genome


@dataclass
class OrqestEvalBatch(EvaluationBatch):
    """:class:`EvaluationBatch` extended with the typed :class:`MetricBundle`s.

    GEPA only reads ``outputs`` / ``scores`` / ``trajectories`` /
    ``objective_scores`` — ``bundles`` is a sidecar so reflective dataset
    construction (and downstream consumers like notebooks) can show
    per-dimension detail without re-evaluating.
    """

    bundles: list[MetricBundle] = field(default_factory=list)


class OrqestGEPAAdapter:
    """:class:`gepa.core.adapter.GEPAAdapter` implementation backed by an
    Orqest :class:`Evaluator` + :class:`Genome`.

    Constructed and held by :class:`OptimizationRunner`; never invoked
    directly by user code. The Protocol is structural in GEPA, so we
    declare conformance by shape rather than inheritance — keeps the
    optional-dependency story clean (no GEPA import needed at module
    load time for `from orqest.optimization import OrqestGEPAAdapter`).
    """

    propose_new_texts: ClassVar[None] = None
    """GEPA's reflective-mutation loop checks ``adapter.propose_new_texts is
    not None`` to decide whether to use a user-provided text proposer; when
    ``None`` it falls back to its built-in LLM-driven proposer (which is
    what we want — GEPA's default uses ``reflection_lm`` to evolve the
    prompt). Declared as a class attribute so the access site doesn't
    raise ``AttributeError``; if we ever ship a custom proposer it becomes
    a method on this class."""

    def __init__(
        self,
        genome: Genome,
        evaluator: Evaluator[Any, Any],
        weights: MetricWeights,
        *,
        bus: EventBus | None = None,
        emit_per_example_events: bool = False,
    ) -> None:
        """Wire the adapter to an :class:`Evaluator` + an optional bus."""
        self._genome = genome
        self._evaluator = evaluator
        self._weights = weights
        self._bus = bus
        self._emit_per_example_events = emit_per_example_events
        self._iteration = 0

    # ------------------------------------------------------------------
    # GEPAAdapter Protocol surface
    # ------------------------------------------------------------------

    def evaluate(
        self,
        batch: list[GoldExample[Any, Any]],
        candidate: dict[str, str],
        capture_traces: bool = False,
    ) -> OrqestEvalBatch:
        """Run *candidate* on *batch* and return an :class:`OrqestEvalBatch`.

        Per the GEPA Protocol contract:

        * ``scores`` length == ``len(batch)``; higher is better.
        * ``trajectories`` populated only when ``capture_traces=True``.
        * ``objective_scores`` populated unconditionally — Orqest's
          multi-signal nature makes them effectively free.
        * Per-example failures yield ``score=0.0`` rather than raising.
        """
        decoded = self._genome.decode(candidate)
        bundles = self._run_async(self._evaluator.evaluate_batch(decoded, batch))

        scores: list[float] = [b.scalarize(self._weights) for b in bundles]
        objective_scores: list[dict[str, float]] = [
            b.to_per_instance_scores(self._weights) for b in bundles
        ]
        outputs: list[dict[str, Any]] = [
            {"accuracy": b.accuracy, "raw": b.raw} for b in bundles
        ]

        trajectories: list[dict[str, Any]] | None = None
        if capture_traces:
            trajectories = [
                self._build_trajectory(ex, b)
                for ex, b in zip(batch, bundles, strict=True)
            ]

        self._iteration += 1
        if self._bus is not None:
            self._emit_iteration_summary(scores, bundles)

        return OrqestEvalBatch(
            outputs=outputs,
            scores=scores,
            trajectories=trajectories,
            objective_scores=objective_scores,
            bundles=bundles,
        )

    def make_reflective_dataset(
        self,
        candidate: dict[str, str],
        eval_batch: OrqestEvalBatch,
        components_to_update: list[str],
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        """Build the per-component reflective dataset for the teacher LLM.

        Schema follows GEPA's recommendation: each record carries
        ``Inputs`` / ``Generated Outputs`` / ``Feedback``. The Feedback
        slot is where Orqest's typed signals shine — we surface the
        per-dimension :class:`MetricBundle` breakdown plus any
        ``uncertainty_targets`` the agent self-reported.
        """
        if eval_batch.trajectories is None:
            return {name: [] for name in components_to_update}

        constraints_by_name = self._gene_constraints()

        dataset: dict[str, list[Mapping[str, Any]]] = {}
        for name in components_to_update:
            records: list[Mapping[str, Any]] = []
            for traj in eval_batch.trajectories:
                record: dict[str, Any] = {
                    "Inputs": {"input": traj.get("input")},
                    "Generated Outputs": {
                        "output": traj.get("output"),
                        "uncertainty_targets": traj.get("uncertainty_targets", []),
                    },
                    "Feedback": traj.get("feedback", ""),
                    "score": traj.get("score"),
                }
                if name in constraints_by_name:
                    record["Constraints"] = constraints_by_name[name]
                records.append(record)
            dataset[name] = records
        return dataset

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _gene_constraints(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for gene in self._genome.genes:
            constraints = getattr(gene, "constraints", None)
            if constraints:
                out[gene.name] = constraints
        return out

    def _build_trajectory(
        self,
        example: GoldExample[Any, Any],
        bundle: MetricBundle,
    ) -> dict[str, Any]:
        feedback = self._format_feedback(bundle)
        return {
            "input": str(example.input)[:500],
            "expected": (
                str(example.expected)[:500]
                if example.expected is not None
                else None
            ),
            "output": bundle.raw.get("output_preview", ""),
            "uncertainty_targets": bundle.raw.get("uncertainty_targets", []),
            "score": bundle.scalarize(self._weights),
            "feedback": feedback,
        }

    @staticmethod
    def _format_feedback(bundle: MetricBundle) -> str:
        parts = [f"accuracy={bundle.accuracy:.2f}"]
        if bundle.confidence is not None:
            parts.append(f"confidence={bundle.confidence:.2f}")
        if bundle.cost_usd > 0:
            parts.append(f"cost_usd={bundle.cost_usd:.4f}")
        if bundle.latency_ms > 0:
            parts.append(f"latency_ms={bundle.latency_ms:.0f}")
        if "error" in bundle.raw:
            parts.append(f"error={bundle.raw['error']}")
        return " | ".join(parts)

    def _emit_iteration_summary(
        self, scores: list[float], bundles: list[MetricBundle]
    ) -> None:
        assert self._bus is not None
        try:
            mean_score = sum(scores) / len(scores) if scores else 0.0
            mean_accuracy = (
                sum(b.accuracy for b in bundles) / len(bundles)
                if bundles
                else 0.0
            )
            self._run_async_fire_and_forget(
                self._bus.emit(
                    AgentEvent(
                        event_type="optimization.iteration_completed",
                        agent_name="optimizer",
                        data={
                            "iteration": self._iteration,
                            "examples": len(scores),
                            "mean_score": mean_score,
                            "mean_accuracy": mean_accuracy,
                        },
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("optimization iteration emit failed: {e}", e=exc)

    def _run_async(self, coro: Any) -> Any:
        """Two-mode async bridge.

        * **CLI / pytest**: no running loop → ``asyncio.run`` directly.
        * **Jupyter**: a loop is already running → run the coroutine on a
          worker thread so it doesn't deadlock on its own loop.

        This is the standard pattern for sync-API libraries (GEPA) calling
        async user code (Orqest). Documented in the concept doc gotcha
        section because it bites people.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop → fresh process / CLI path.
            return asyncio.run(coro)
        # Already in an event loop (Jupyter): run on a worker thread.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()

    def _run_async_fire_and_forget(self, coro: Any) -> None:
        """Best-effort fire-and-forget async dispatch — used for telemetry
        emits where blocking is wrong but losing the event is acceptable.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            with contextlib.suppress(Exception):
                asyncio.run(coro)
            return
        loop.create_task(coro)
