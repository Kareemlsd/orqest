"""Topology evolution: gene + evaluator atop the orchestration spec layer.

Two pieces:

* :class:`TopologyGene` — a Pydantic gene whose value is a serialized
  :data:`TopologySpec` JSON string. Mirrors the encode/decode contract of
  :class:`PromptGene`, so it slots into existing :class:`Genome` machinery
  (when the consumer wants to combine prompt + topology evolution in one
  GEPA run via :class:`TopologyGEPAAdapter`).
* :class:`TopologyEvaluator` — an :class:`Evaluator` subclass that hydrates
  the genome's topology spec into a live runtime, runs it on each example,
  and unpacks composite results (``ParallelResult.merged`` /
  ``LoopResult.output``) before scoring. Adds ``n_agents`` and ``depth`` to
  :attr:`MetricBundle.raw` as proxies for cost / latency ceilings — these
  flow through to the optimizer's Pareto frontier without any further
  wiring.

YAGNI note: :class:`TopologyGene` is **not** added to the existing :data:`Gene`
discriminated union in :mod:`orqest.optimization.genome`. The recommended path
for combining ADAS+GEPA is the two-phase one (ADAS first, GEPA on the winner),
which uses two distinct genome shapes — there's no need for a unified Gene
union today. If users prove the combined-single-genome case matters, extending
the union is a one-line change.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from orqest.agents.base_agent import BaseAgent
from orqest.autonomy.factory import AgentFactory
from orqest.metacognition.protocol import ConfidenceProtocol
from orqest.optimization.bundle import MetricBundle
from orqest.optimization.evaluator import Evaluator, GoldExample
from orqest.orchestration.hydrate import (
    CallableRegistry,
    _count_agent_steps,
    _topology_depth,
    topology_from_spec,
)
from orqest.orchestration.loop import LoopResult
from orqest.orchestration.parallel import ParallelResult
from orqest.orchestration.spec import TopologySpec

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT", bound=BaseModel)

_TOPOLOGY_ADAPTER: TypeAdapter[TopologySpec] = TypeAdapter(TopologySpec)


class TopologyGene(BaseModel):
    """A topology-shaped gene whose initial value is a :data:`TopologySpec`.

    Encodes to JSON (the GEPA wire format is ``dict[str, str]``) and decodes
    back via Pydantic validation. **Resilient on malformed reflection output**:
    a candidate that fails JSON parsing or schema validation falls back to
    the gene's ``initial`` rather than raising — same defensive posture as
    :class:`PromptGene` (we'd rather lose one iteration than crash a search).
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["topology"] = "topology"
    name: str
    """Logical slot identifier — the key the meta agent emits and the
    :class:`TopologyEvaluator` reads from the decoded genome."""

    initial: TopologySpec
    """Seed topology. The meta-agent's W0 candidate; also the resilient
    fallback for malformed reflection output."""

    constraints: str | None = None
    """Optional natural-language guardrail surfaced to the meta agent in
    its design prompt (e.g. *"must include the existing classifier as a
    Pipeline first step"*)."""

    allowed_step_kinds: tuple[str, ...] = ("agent_step", "function_step")
    """Whitelisted leaf-step kinds. Surfaced to the meta agent in its prompt
    as the only legal atomic operations. Default permits both."""

    max_depth: int = 4
    """Maximum nesting depth the meta agent is allowed to emit. Past this
    depth the evaluator rejects the candidate (``max_depth_exceeded`` error)
    so the optimizer pivots away from runaway-recursion designs."""

    def encode(self) -> str:
        """Serialize the seed topology to JSON for GEPA's wire format."""
        return self.initial.model_dump_json()

    def decode(self, candidate: str | None) -> TopologySpec:
        """Decode a meta-agent-proposed JSON string back to a TopologySpec.

        Three failure modes, all resilient:

        * ``None`` (key missing from the candidate dict) → ``initial``
        * Malformed JSON → ``initial``
        * Valid JSON but failing TopologySpec schema → ``initial``
        """
        if candidate is None:
            return self.initial
        try:
            return _TOPOLOGY_ADAPTER.validate_json(candidate)
        except (ValidationError, json.JSONDecodeError, ValueError):
            return self.initial


def _no_op_factory(_decoded: dict[str, Any]) -> BaseAgent[Any, Any]:
    """Placeholder for :class:`Evaluator`'s required ``agent_factory``.

    :class:`TopologyEvaluator` overrides ``evaluate_one`` completely, so the
    inherited factory slot is never invoked. We pass this no-op to satisfy
    the parent constructor's signature without lying about the intent.
    """
    raise RuntimeError(
        "TopologyEvaluator does not use a single-agent factory; "
        "this no-op should never be called."
    )


def unpack_topology_output(run_result: Any) -> Any:
    """Extract the meaningful payload from a topology's ``.run()`` result.

    * :class:`ParallelResult` → ``.merged`` (the merge-strategy output)
    * :class:`LoopResult` → ``.output`` (the converged value)
    * :class:`AgentRunResult` (if a topology somehow returns one) → ``.output``
    * Anything else → identity (Pipeline / Router return their final value)
    """
    if isinstance(run_result, ParallelResult):
        return run_result.merged
    if isinstance(run_result, LoopResult):
        return run_result.output
    if hasattr(run_result, "output"):
        return run_result.output
    return run_result


class TopologyEvaluator(Evaluator[InputT, OutputT], Generic[InputT, OutputT]):
    """Score a topology candidate against gold examples.

    Replaces :class:`Evaluator`'s single-BaseAgent execution path with topology
    hydration. Adds ``n_agents`` and ``depth`` structural metrics to
    :attr:`MetricBundle.raw` so the optimizer's Pareto front can prefer
    smaller / shallower topologies on accuracy ties.

    **Cost handling:** Unlike single-agent evaluation, a topology run does
    not have a single ``Usage`` object. We surface ``cost_usd=0.0`` by
    default; consumers wanting cost-as-fitness should pass a
    ``cost_estimator`` callable that walks the topology and sums per-agent
    usage (see the concept doc for the recipe). This is a known limitation
    documented in the W3 risks section.
    """

    def __init__(
        self,
        *,
        score_fn: Callable[
            [Any, GoldExample[Any, Any]],
            float | Awaitable[float],
        ],
        callable_registry: CallableRegistry,
        agent_registry: dict[str, Callable[[], BaseAgent[Any, Any]]],
        topology_gene_name: str = "main",
        agent_factory: AgentFactory | None = None,
        confidence_protocol: ConfidenceProtocol | None = None,
        cost_estimator: Callable[[Any], float] | None = None,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        """Wire the per-evaluation building blocks.

        Args:
            score_fn: ``(output, example) -> float in [0, 1]``. Identical
                contract to the parent :class:`Evaluator`.
            callable_registry: Registry of named conditions / merges /
                state-updaters / function-steps. The meta agent's allowlist.
            agent_registry: Map from agent name to a factory producing a
                fresh :class:`BaseAgent`. Factories (not instances) avoid
                cached-``_agent`` problems when the same agent appears in
                multiple candidates across a search.
            topology_gene_name: Key under which the decoded genome carries
                the :data:`TopologySpec`. Default ``"main"``.
            agent_factory: Optional :class:`AgentFactory` for hydrating
                :class:`AgentSpec` inline-spawn references inside topology
                specs. Required only when topology candidates use
                ``inline_spec`` rather than ``agent_name``.
            confidence_protocol: Reserved for future use — topologies don't
                produce confidence directly today (would require per-step
                EnrichedOutput plumbing); accepted for signature parity.
            cost_estimator: Optional callable for translating downstream
                usage into USD. See class docstring caveat.
            timer: Monotonic clock; override only in tests.

        """
        super().__init__(
            agent_factory=_no_op_factory,
            score_fn=score_fn,
            confidence_protocol=confidence_protocol,
            cost_estimator=cost_estimator,
            timer=timer,
        )
        self._callable_registry = callable_registry
        self._agent_registry = agent_registry
        self._spawn_factory = agent_factory
        self._topology_gene_name = topology_gene_name

    async def evaluate_one(
        self,
        decoded: dict[str, Any],
        example: GoldExample[InputT, OutputT],
    ) -> MetricBundle:
        """Hydrate the topology, run on the example, return a MetricBundle.

        Failures (hydration errors, runtime errors, score errors) yield a
        zero-accuracy bundle with the failure captured in
        :attr:`MetricBundle.raw["error"]`. This matches the parent's
        never-raise contract — GEPA's adapter Protocol forbids raising on
        per-example evaluation failures.
        """
        start = self._timer()
        spec_raw = decoded.get(self._topology_gene_name)

        # Track structural metrics even on failure paths so the optimizer
        # sees the topology's shape regardless of whether it ran.
        n_agents = (
            _count_agent_steps(spec_raw)
            if spec_raw is not None and not isinstance(spec_raw, str)
            else 0
        )
        depth = (
            _topology_depth(spec_raw)
            if spec_raw is not None and not isinstance(spec_raw, str)
            else 0
        )

        if spec_raw is None:
            elapsed_ms = (self._timer() - start) * 1000.0
            return MetricBundle(
                accuracy=0.0,
                latency_ms=elapsed_ms,
                raw={
                    "error": (
                        f"decoded genome missing topology gene "
                        f"{self._topology_gene_name!r}"
                    ),
                    "error_type": "MissingGene",
                    "n_agents": 0,
                    "depth": 0,
                },
            )

        try:
            topology = topology_from_spec(
                spec_raw,
                callable_registry=self._callable_registry,
                agent_registry=self._agent_registry,
                agent_factory=self._spawn_factory,
            )
            run_result = await topology.run(example.input)
            output = unpack_topology_output(run_result)
            score_value = await self._await_if_needed(
                self._score_fn(output, example)
            )
            accuracy = max(0.0, min(1.0, float(score_value) * example.weight))
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (self._timer() - start) * 1000.0
            return MetricBundle(
                accuracy=0.0,
                latency_ms=elapsed_ms,
                raw={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "n_agents": n_agents,
                    "depth": depth,
                },
            )

        elapsed_ms = (self._timer() - start) * 1000.0
        cost_usd = 0.0  # see class docstring re: cost limitation

        return MetricBundle(
            accuracy=accuracy,
            cost_usd=cost_usd,
            latency_ms=elapsed_ms,
            raw={
                "n_agents": n_agents,
                "depth": depth,
            },
        )


__all__ = [
    "TopologyEvaluator",
    "TopologyGene",
    "unpack_topology_output",
]
