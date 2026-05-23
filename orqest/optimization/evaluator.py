"""Run a candidate against gold examples and produce :class:`MetricBundle`s.

The evaluator is the bridge between Orqest's typed agents and GEPA's
``dict[str, str]`` candidates. The user supplies:

* an ``agent_factory(decoded: dict[str, Any]) -> BaseAgent`` that constructs
  a fresh agent from a decoded genome — fresh because mutating an existing
  agent's ``system_prompt`` is unsafe (the cached ``pydantic_ai.Agent`` keeps
  the old prompt; see :func:`apply_result` for the same gotcha)
* a ``score_fn(output, example) -> float in [0, 1]`` that scores accuracy

Optional:

* a ``ConfidenceProtocol`` for filling :attr:`MetricBundle.confidence`
  (cheapest: :class:`StructuredOutputProtocol`)
* a ``cost_estimator(usage)`` translating ``pydantic_ai.usage.RunUsage`` to USD
* a custom timer (defaults to ``time.monotonic``)

GEPA's built-in ``cache_evaluation=True`` deduplicates ``(candidate, example)``
evaluations during Pareto selection, so this evaluator does not maintain its
own cache — keeping the surface clean.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from orqest.agents.base_agent import BaseAgent
from orqest.metacognition.protocol import ConfidenceProtocol
from orqest.optimization.bundle import MetricBundle

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT", bound=BaseModel)


class GoldExample(BaseModel, Generic[InputT, OutputT]):
    """One labeled example for the optimizer's eval set.

    Generic over input/output so consumers can pass typed Pydantic shapes
    without losing type information at the score-function boundary.
    """

    input: InputT
    """Whatever the agent accepts. Often a string prompt; can be a richer
    Pydantic model when the consumer wants to pass structured context."""

    expected: OutputT | None = None
    """Ground-truth output, when one exists. ``None`` is fine for examples
    where success is judged by the rubric (LLM-judge) rather than equality."""

    rubric: str | None = None
    """Free-text scoring guidance for an LLM-judge ``score_fn``. Ignored by
    purely-programmatic ``score_fn``s."""

    weight: float = 1.0
    """Per-example weight surfaced to the score function — useful for
    upweighting hard / adversarial examples in the gold set."""

    id: str | None = None
    """Optional stable identifier. Defaults to ``id(example)`` when needed."""


def _default_cost_estimator(usage: Any) -> float:
    """Token-count fallback when no cost_estimator is supplied.

    Returns 0.0 — we don't presume token prices. Consumers who care about
    cost-as-fitness wire a real estimator that knows their model's USD
    rate. Free signal: still surfaces token totals via :attr:`MetricBundle.raw`.
    """
    return 0.0


class Evaluator(Generic[InputT, OutputT]):
    """Score one candidate against a gold set, producing :class:`MetricBundle`s.

    Construction takes the consumer-side wiring; per-call ``decoded`` is the
    decoded genome from :meth:`Genome.decode`.
    """

    def __init__(
        self,
        agent_factory: Callable[[dict[str, Any]], BaseAgent[Any, OutputT]],
        score_fn: Callable[
            [OutputT, GoldExample[InputT, OutputT]],
            float | Awaitable[float],
        ],
        *,
        confidence_protocol: ConfidenceProtocol | None = None,
        cost_estimator: Callable[[Any], float] | None = None,
        timer: Callable[[], float] = time.monotonic,
        n_trials_per_example: int = 1,
    ) -> None:
        """Wire the per-evaluation building blocks.

        Args:
            agent_factory: Callable taking a decoded genome and returning a
                **fresh** :class:`BaseAgent`. Must not mutate or share state
                across calls — one factory invocation per evaluation.
            score_fn: ``(output, example) -> float in [0, 1]``. May be sync
                or async.
            confidence_protocol: Optional :class:`ConfidenceProtocol` for
                self-rated calibration. When set, :attr:`MetricBundle.confidence`
                is filled via ``BaseAgent.run_enriched``.
            cost_estimator: Optional ``(RunUsage) -> float`` translating
                token usage to USD. When omitted, :attr:`MetricBundle.cost_usd`
                stays 0 (token counts still surface via :attr:`MetricBundle.raw`).
            timer: Monotonic clock for latency measurement. Override only
                in tests.
            n_trials_per_example: When ``> 1``, evaluate each example that many
                times and aggregate via :meth:`MetricBundle.aggregate` to wash
                out LLM run-to-run variance. The returned bundle carries
                ``n_trials`` and per-dimension ``stdev``. ``1`` (default)
                preserves the legacy single-shot behavior at no extra cost.
                Each trial gets a fresh agent (``agent_factory(decoded)``
                called per trial) so trials are independent. Cost scales
                linearly; useful for weaker models where single trials swing
                ±10pp.

        """
        if n_trials_per_example < 1:
            raise ValueError(
                f"n_trials_per_example must be >= 1, got {n_trials_per_example}"
            )
        self._agent_factory = agent_factory
        self._score_fn = score_fn
        self._confidence_protocol = confidence_protocol
        self._cost_estimator = cost_estimator or _default_cost_estimator
        self._timer = timer
        self._n_trials_per_example = n_trials_per_example

    async def evaluate_one(
        self,
        decoded: dict[str, Any],
        example: GoldExample[InputT, OutputT],
    ) -> MetricBundle:
        """Run one example, return the per-example :class:`MetricBundle`.

        Failures (agent exceptions, score_fn exceptions) are swallowed and
        produce a zero-accuracy bundle with the error captured in
        :attr:`MetricBundle.raw["error"]`. GEPA's adapter Protocol explicitly
        requires evaluators to **never raise** for individual example failures
        — see :class:`gepa.core.adapter.GEPAAdapter` docstring.

        When ``n_trials_per_example > 1`` (configured at construction), this
        method runs ``_evaluate_single_trial`` N times and aggregates via
        :meth:`MetricBundle.aggregate`. Failed trials are folded into the
        average (counted as zero-accuracy). When every trial fails, the
        aggregate is the first failure's error bundle plus an
        ``aggregation_note`` in ``raw``.
        """
        if self._n_trials_per_example == 1:
            return await self._evaluate_single_trial(decoded, example)

        trials: list[MetricBundle] = []
        for _ in range(self._n_trials_per_example):
            trials.append(await self._evaluate_single_trial(decoded, example))

        # If literally every trial failed, the user almost certainly wants to
        # see the first failure's error, not a misleadingly-averaged 0.0
        # accuracy. Pass through but annotate as multi-trial.
        if all(t.raw.get("error") for t in trials):
            head = trials[0]
            return head.model_copy(
                update={
                    "raw": {
                        **head.raw,
                        "aggregation_note": (
                            f"all {len(trials)} trials failed; representative "
                            f"error from trial 1"
                        ),
                        "n_trials_attempted": len(trials),
                    }
                }
            )
        return MetricBundle.aggregate(trials)

    async def _evaluate_single_trial(
        self,
        decoded: dict[str, Any],
        example: GoldExample[InputT, OutputT],
    ) -> MetricBundle:
        """Run one trial of one example. Internal helper for :meth:`evaluate_one`."""
        start = self._timer()

        try:
            agent = self._agent_factory(decoded)
            run_result = await self._run_agent(agent, example)
            output = run_result.output if hasattr(run_result, "output") else run_result
            score_value = await self._await_if_needed(self._score_fn(output, example))
            accuracy = max(0.0, min(1.0, float(score_value) * example.weight))
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (self._timer() - start) * 1000.0
            return MetricBundle(
                accuracy=0.0,
                cost_usd=0.0,
                latency_ms=elapsed_ms,
                raw={"error": str(exc), "error_type": type(exc).__name__},
            )

        elapsed_ms = (self._timer() - start) * 1000.0
        usage = self._extract_usage(run_result)
        cost_usd = self._cost_estimator(usage) if usage is not None else 0.0

        confidence: float | None = None
        if self._confidence_protocol is not None:
            confidence = self._extract_confidence(run_result)

        raw: dict[str, Any] = {}
        if usage is not None:
            raw["input_tokens"] = getattr(usage, "input_tokens", 0)
            raw["output_tokens"] = getattr(usage, "output_tokens", 0)

        return MetricBundle(
            accuracy=accuracy,
            confidence=confidence,
            cost_usd=cost_usd,
            latency_ms=elapsed_ms,
            raw=raw,
        )

    async def evaluate_batch(
        self,
        decoded: dict[str, Any],
        batch: list[GoldExample[InputT, OutputT]],
    ) -> list[MetricBundle]:
        """Evaluate a batch sequentially. Caller controls concurrency at a
        higher layer (parallel evaluation across candidates is GEPA's job).
        """
        return [await self.evaluate_one(decoded, ex) for ex in batch]

    # --- internals -----------------------------------------------------

    async def _run_agent(
        self,
        agent: BaseAgent[Any, OutputT],
        example: GoldExample[InputT, OutputT],
    ) -> Any:
        """Default run path: call ``agent.call_model`` directly so we get
        both the typed output AND the underlying ``AgentRunResult`` (which
        carries ``usage()`` for cost accounting).

        Calling ``agent.run`` would return the bare output and discard the
        usage object — fine for production, fatal for an optimizer that
        needs token accounting as fitness signal.

        Subclasses can override for custom state shapes / multi-turn flows.
        """
        from orqest.agents.state import GlobalState

        state = GlobalState()
        return await agent.call_model(str(example.input), state)

    @staticmethod
    async def _await_if_needed(value: float | Awaitable[float]) -> float:
        if hasattr(value, "__await__"):
            return await value  # type: ignore[no-any-return]
        return float(value)

    @staticmethod
    def _extract_usage(run_result: Any) -> Any | None:
        """Best-effort extraction of usage from either AgentRunResult or
        a bare output.
        """
        if hasattr(run_result, "usage") and callable(run_result.usage):
            try:
                return run_result.usage()
            except Exception:  # noqa: BLE001
                return None
        return getattr(run_result, "usage", None)

    @staticmethod
    def _extract_confidence(run_result: Any) -> float | None:
        """Pull confidence from ``run_result.output`` if it exposes one.

        Tries (in order): ``output.confidence``, ``output.self_confidence``,
        ``output.metadata['confidence']``. Returns None if no signal.
        """
        output = getattr(run_result, "output", run_result)
        for attr in ("confidence", "self_confidence"):
            value = getattr(output, attr, None)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        meta = getattr(output, "metadata", None)
        if isinstance(meta, dict) and "confidence" in meta:
            try:
                return float(meta["confidence"])
            except (TypeError, ValueError):
                pass
        return None
