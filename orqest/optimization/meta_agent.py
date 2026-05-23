"""ADAS-style Meta Agent Search loop for topology evolution.

Faithful to ADAS in shape (design → reflexion → evaluate → archive,
[arXiv 2408.08435](https://arxiv.org/abs/2408.08435)) but **not in surface**:
the meta agent emits typed :data:`TopologySpec` JSON, never raw Python. This
sidesteps ADAS's `exec()`-in-process gap (paper claimed containerization;
public repo ships in-process exec) — there is no code to sandbox because
there is no code, only Pydantic-validated structure.

The loop owes its archive-strategy menu to the
[2510.06711 critique](https://arxiv.org/abs/2510.06711):
``top_k`` (default) and ``parallel`` outperform ADAS's original ``cumulative``
on most benchmarks. Users who want to reproduce the ADAS paper verbatim flip
``MetaAgentConfig.archive_strategy="cumulative"``.

Three pieces in this module:

* :class:`MetaAgentConfig` — frozen dataclass, search-loop knobs.
* :class:`Archive` + :class:`ArchiveEntry` — manages the candidate population
  with strategy-pluggable retention and prompt-serialization.
* :class:`MetaAgentSearch` — the loop. Returns an :class:`OptimizationResult`
  shaped identically to GEPA's so downstream consumers (apply_result, notebook
  visualizations) work without dispatch.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from pydantic_ai import Agent as PydanticAIAgent

from orqest.observability.events import AgentEvent, EventBus
from orqest.optimization.bundle import MetricBundle, MetricWeights
from orqest.optimization.evaluator import GoldExample
from orqest.optimization.runner import OptimizationResult
from orqest.optimization.topology import TopologyEvaluator, TopologyGene
from orqest.orchestration.spec import TopologySpec
from orqest.utils.llm_model import resolve_model

ArchiveStrategy = Literal["cumulative", "top_k", "parallel"]


@dataclass(frozen=True)
class MetaAgentConfig:
    """Knobs for :class:`MetaAgentSearch`.

    Distinct from :class:`OptimizationConfig` (which governs GEPA's prompt
    evolution loop) because the search-loop parameters are different in kind
    — generations of designed-and-evaluated topologies, not GEPA's sampled
    minibatches.
    """

    n_generations: int = 10
    """Number of design-evaluate cycles after the seed evaluation."""

    archive_strategy: ArchiveStrategy = "top_k"
    """How to surface the archive to the next design step.

    * ``"top_k"`` (default) — show only the top ``archive_size`` by
      aggregate score. Per the 2510.06711 critique, the strongest signal-to-
      noise ratio for the meta agent.
    * ``"cumulative"`` — show every entry seen so far. ADAS-paper-faithful;
      tends to overflow context after ~20 entries and dilute strong signals.
    * ``"parallel"`` — show nothing. Meta agent designs from scratch each
      generation; selection happens at the end. Surprisingly competitive
      per the critique."""

    archive_size: int = 5
    """Cap for ``top_k`` and the ring-buffer for ``cumulative`` if you want
    one (unlimited by default for ``cumulative``). Ignored for ``parallel``."""

    reflexion_passes: int = 2
    """Number of reflexion-revision passes after the design step. ADAS uses 2
    by default; 0 disables reflexion entirely (raw design only)."""

    debug_max: int = 3
    """How many times to retry a generation that fails Pydantic validation
    or hydration. The ValidationError surface is fed back to the meta agent
    as feedback (analogue of ADAS's traceback retry)."""

    minibatch_size: int = 5
    """Validation subset size per candidate evaluation. Caps cost: each
    candidate evaluates against this many examples (sampled deterministically
    from the valset), not the full set. The seed and final winner are
    re-evaluated against the full set."""

    seed: int = 42
    """Random seed for minibatch sampling and reproducibility."""

    weights: MetricWeights = field(default_factory=MetricWeights)
    """Aggregation weights for converting per-example MetricBundles to a
    scalar score for archive ranking. Defaults match GEPA's recommended
    weights so users see consistent ranking across optimizers."""

    def __post_init__(self) -> None:
        if self.n_generations < 1:
            raise ValueError("n_generations must be >= 1")
        if self.archive_size < 1:
            raise ValueError("archive_size must be >= 1")
        if self.reflexion_passes < 0:
            raise ValueError("reflexion_passes must be >= 0")
        if self.debug_max < 0:
            raise ValueError("debug_max must be >= 0")
        if self.minibatch_size < 1:
            raise ValueError("minibatch_size must be >= 1")
        if self.archive_strategy not in ("cumulative", "top_k", "parallel"):
            raise ValueError(
                f"archive_strategy must be one of "
                f"('cumulative', 'top_k', 'parallel'), got {self.archive_strategy!r}"
            )


class ArchiveEntry(BaseModel):
    """One archived candidate."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    generation: int
    """Generation index. ``-1`` means the seed (pre-search baseline)."""

    spec_json: str
    """The TopologySpec serialized to JSON — the GEPA wire format."""

    bundles: list[MetricBundle]
    """Per-example MetricBundles from this entry's evaluation."""

    aggregate_score: float
    """Mean scalarized score across ``bundles`` — the archive ranking key."""

    thought: str = ""
    """Meta-agent's design reasoning. Empty for the seed."""

    parent_idx: int | None = None
    """Index of the archive entry whose design inspired this one. ``None``
    for the seed and for ``parallel``-strategy entries (no parent context)."""


class TopologyDesign(BaseModel):
    """Structured output for the meta agent.

    The meta agent's pydantic-ai :class:`Agent` returns this shape every
    design / reflexion / debug step.
    """

    thought: str
    """Free-text reasoning — quoted into the archive entry for inspection."""

    spec: TopologySpec
    """The proposed topology. Pydantic-validated; malformed candidates fail
    fast with a ValidationError that the debug-retry loop surfaces back to
    the meta agent."""


class Archive:
    """Strategy-pluggable archive of evaluated candidates.

    All entries are retained in storage (so :meth:`pareto` and :meth:`best`
    see the full history); ``serialize_for_prompt`` is the strategy-aware
    view shown to the meta agent on the next design step.
    """

    def __init__(
        self, strategy: ArchiveStrategy = "top_k", size: int = 5
    ) -> None:
        if strategy not in ("cumulative", "top_k", "parallel"):
            raise ValueError(f"unknown strategy {strategy!r}")
        if size < 1:
            raise ValueError("size must be >= 1")
        self._strategy = strategy
        self._size = size
        self._entries: list[ArchiveEntry] = []

    def add(self, entry: ArchiveEntry) -> int:
        """Append *entry* and return its archive index."""
        self._entries.append(entry)
        return len(self._entries) - 1

    @property
    def entries(self) -> list[ArchiveEntry]:
        """All entries in insertion order. Read-only view."""
        return list(self._entries)

    def serialize_for_prompt(self) -> str:
        """The archive view passed to the meta agent for its next design.

        Strategy-dependent:

        * ``"cumulative"`` — every entry, JSON-serialized.
        * ``"top_k"`` — top ``size`` entries by aggregate_score, JSON-serialized.
        * ``"parallel"`` — empty string. Meta agent designs without context.
        """
        if self._strategy == "parallel":
            return ""
        ranked = sorted(self._entries, key=lambda e: -e.aggregate_score)
        if self._strategy == "top_k":
            ranked = ranked[: self._size]
        return ",\n".join(
            json.dumps(
                {
                    "generation": e.generation,
                    "thought": e.thought[:500],
                    "spec": json.loads(e.spec_json),
                    "score": round(e.aggregate_score, 4),
                }
            )
            for e in ranked
        )

    def best(self) -> ArchiveEntry:
        """The highest-aggregate-score entry. Raises if empty."""
        if not self._entries:
            raise ValueError("Archive is empty; call .add() first")
        return max(self._entries, key=lambda e: e.aggregate_score)

    def pareto(self) -> list[ArchiveEntry]:
        """Distinct entries on the accuracy / cost / latency Pareto front.

        An entry is on the front if no other entry dominates it (strictly
        better on every axis). We negate cost and latency so "more is
        better" applies uniformly.
        """
        if not self._entries:
            return []

        def axes(e: ArchiveEntry) -> tuple[float, float, float]:
            mean_acc = sum(b.accuracy for b in e.bundles) / max(1, len(e.bundles))
            mean_cost = sum(b.cost_usd for b in e.bundles) / max(1, len(e.bundles))
            mean_lat = sum(b.latency_ms for b in e.bundles) / max(1, len(e.bundles))
            return (mean_acc, -mean_cost, -mean_lat)

        front: list[ArchiveEntry] = []
        for e in self._entries:
            ea = axes(e)
            dominated = False
            for other in self._entries:
                if other is e:
                    continue
                oa = axes(other)
                # other dominates e if it's >= on every axis and > on at least one
                if all(o >= a for o, a in zip(oa, ea)) and any(
                    o > a for o, a in zip(oa, ea)
                ):
                    dominated = True
                    break
            if not dominated:
                front.append(e)
        return front

    def __len__(self) -> int:
        return len(self._entries)


# --- Prompt construction ----------------------------------------------------


_TOPOLOGY_SCHEMA_JSON: str | None = None


def _topology_schema() -> str:
    """Lazy-cached JSON schema for TopologySpec — passed to the meta agent."""
    global _TOPOLOGY_SCHEMA_JSON
    if _TOPOLOGY_SCHEMA_JSON is None:
        schema = TypeAdapter(TopologySpec).json_schema()
        _TOPOLOGY_SCHEMA_JSON = json.dumps(schema, indent=2)
    return _TOPOLOGY_SCHEMA_JSON


_DESIGN_SYSTEM = """\
You are an expert agentic-system designer. Your job is to compose Orqest's
orchestration primitives (Pipeline, Parallel, Router, RefinementLoop) into a
topology that maximizes a multi-bucket task evaluation.

You design topologies by emitting a TopologySpec — a typed JSON document
following the schema embedded in the user message. **Never emit Python code.**
Only emit valid TopologySpec JSON in the `spec` field of your structured
response.

Anti-patterns to avoid:
1. Don't emit unknown agent_name or callable_name values — they will fail
   hydration. Only use names from the agent_registry / callable_registry
   allowlists provided in the user message.
2. Don't nest topologies past the configured max_depth.
3. Don't emit empty Pipeline / Parallel / Router (each requires >= 1 step
   or route).
4. Don't reference inline_spec when no AgentFactory is configured (the user
   message will tell you whether inline spawning is allowed).
5. Don't repeat a near-identical topology you already see in the archive —
   always introduce at least one structural change.

Slot semantics (do not confuse):
* AgentStep.agent_name → an agent_registry name (an agent that runs an LLM call)
* FunctionStep.callable_name → a callable_registry name (a pure async function)
* Router.classifier → an AGENT (agent_registry name or AgentSpec) that returns
  a route name; NOT a callable_registry name. If you want rule-based routing,
  use RouteSpec.condition_name (a callable_registry boolean predicate) instead.
* Route.condition_name → a callable_registry boolean predicate
* Parallel.merge → either "collect_all" / "first_wins" (built-ins) OR a
  callable_registry name
* RefinementLoop.evaluator → an agent (registry name or AgentSpec); the
  agent's output must include a `passed` field and optionally `score`
* RefinementLoop.state_updater_name → a callable_registry name
"""


def _format_archive_block(archive_str: str) -> str:
    if not archive_str:
        return "(no archive context — design from scratch)"
    return archive_str


def _build_design_user_prompt(
    *,
    gene: TopologyGene,
    archive_view: str,
    callable_names: list[str],
    agent_names: list[str],
    has_factory: bool,
) -> str:
    constraints = (
        f"\n\nAdditional constraints (must satisfy):\n{gene.constraints}"
        if gene.constraints
        else ""
    )
    inline = "permitted" if has_factory else "DISALLOWED — only use agent_name references"
    return (
        f"Design a TopologySpec for the gene {gene.name!r}.\n\n"
        f"## TopologySpec JSON schema\n```json\n{_topology_schema()}\n```\n\n"
        f"## Allowed agent_name values (from agent_registry)\n"
        f"{json.dumps(sorted(agent_names))}\n\n"
        f"## Allowed callable_name values (from callable_registry)\n"
        f"{json.dumps(sorted(callable_names))}\n\n"
        f"## Inline AgentSpec spawning\n{inline}\n\n"
        f"## Allowed leaf step kinds\n{list(gene.allowed_step_kinds)}\n\n"
        f"## Maximum nesting depth\n{gene.max_depth}\n\n"
        f"## Archive (prior designs)\n{_format_archive_block(archive_view)}\n"
        f"{constraints}\n\n"
        f"Emit a thought (1-3 sentences) and a spec (TopologySpec JSON)."
    )


def _build_reflexion_user_prompt(
    *,
    candidate_design: TopologyDesign,
    pass_idx: int,
) -> str:
    return (
        f"## Reflexion pass {pass_idx + 1}\n\n"
        f"You proposed:\n"
        f"### Thought\n{candidate_design.thought}\n\n"
        f"### Spec\n```json\n{candidate_design.spec.model_dump_json(indent=2)}\n```\n\n"
        f"Critique your own design and emit a revised version. Address:\n"
        f"1. Is this structurally novel vs. typical baselines (single CoT,"
        f"   simple Pipeline)?\n"
        f"2. Does it actually exploit task structure, or just add steps for"
        f"   the sake of it?\n"
        f"3. Are there any obvious correctness issues (unreachable routes,"
        f"   trivial fallback, contradictory routing)?\n\n"
        f"Emit a thought (your critique) and a spec (revised TopologySpec)."
    )


def _build_debug_user_prompt(
    *,
    bad_design: TopologyDesign,
    error: Exception,
) -> str:
    return (
        f"## Debug retry\n\n"
        f"Your previous design FAILED hydration with this error:\n"
        f"```\n{type(error).__name__}: {error}\n```\n\n"
        f"The failing spec was:\n"
        f"```json\n{bad_design.spec.model_dump_json(indent=2)}\n```\n\n"
        f"Emit a corrected design. The most common causes are: unknown"
        f" agent_name / callable_name, missing required fields, or invalid"
        f" enum values."
    )


# --- Search loop ------------------------------------------------------------


class MetaAgentSearch:
    """Run an ADAS-style search over :data:`TopologySpec` candidates.

    Three-stage generation: design → reflexion (×N) → evaluate (with debug
    retry). Pydantic ValidationError + hydration KeyError are caught and fed
    back to the meta agent as debug feedback. Non-debuggable failures
    (after ``debug_max`` retries) skip the generation; the search continues.
    """

    def __init__(
        self,
        config: MetaAgentConfig,
        *,
        gene: TopologyGene,
        evaluator: TopologyEvaluator,
        meta_agent_model: str,
        api_key: str,
        bus: EventBus | None = None,
    ) -> None:
        """Wire the search.

        Args:
            config: Frozen :class:`MetaAgentConfig`.
            gene: The :class:`TopologyGene` being evolved. Carries the seed,
                the constraints, and the allowed-step-kinds whitelist that
                shapes the meta-agent prompt.
            evaluator: A :class:`TopologyEvaluator` configured with the
                user's callable + agent registries and score function.
            meta_agent_model: ``provider:model_id`` string for the meta agent.
                Use the strongest model you can afford — design quality
                scales directly with this knob.
            api_key: API key for the meta agent's model.
            bus: Optional :class:`EventBus`. When provided, the loop emits
                ``meta_agent.iteration_completed`` per generation and
                ``meta_agent.debug_retry`` on Pydantic-error retries.

        """
        self._config = config
        self._gene = gene
        self._evaluator = evaluator
        self._bus = bus
        self._rng = random.Random(config.seed)

        # Meta agent — a pydantic-ai Agent with structured output.
        # We don't go through orqest BaseAgent here because BaseAgent expects
        # StateT/OutputT to thread through call_model with state; we want a
        # one-shot structured-output call per design step.
        meta_model = resolve_model(meta_agent_model, api_key=api_key)
        self._meta_agent = PydanticAIAgent(
            model=meta_model,
            system_prompt=_DESIGN_SYSTEM,
            output_type=TopologyDesign,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        trainset: list[GoldExample[Any, Any]],
        valset: list[GoldExample[Any, Any]] | None = None,
    ) -> OptimizationResult:
        """Run the search; return an :class:`OptimizationResult`.

        ``trainset`` is currently used only to size the minibatch sampler;
        the actual evaluation runs against ``valset`` (or against ``trainset``
        if no valset is provided). The asymmetry mirrors GEPA's setup but
        is less load-bearing here — topology evaluation doesn't have a
        train/val distinction in the gradient sense.
        """
        if not trainset:
            raise ValueError("trainset must contain at least 1 example")
        valset = valset if valset else trainset

        archive = Archive(self._config.archive_strategy, self._config.archive_size)

        # Seed evaluation: full valset, baseline reference for the user.
        seed_bundles = await self._evaluator.evaluate_batch(
            decoded={self._gene.name: self._gene.initial},
            batch=valset,
        )
        seed_score = _aggregate(seed_bundles, self._config.weights)
        archive.add(
            ArchiveEntry(
                generation=-1,
                spec_json=self._gene.encode(),
                bundles=seed_bundles,
                aggregate_score=seed_score,
                thought="(seed)",
                parent_idx=None,
            )
        )
        self._emit_iteration("seed", -1, seed_score, len(archive))

        history: list[dict[str, Any]] = []
        history.append(
            {
                "generation": -1,
                "score": seed_score,
                "skipped": False,
                "thought": "(seed)",
            }
        )

        for gen in range(self._config.n_generations):
            entry, hist_record = await self._one_generation(
                gen, valset, archive
            )
            history.append(hist_record)
            if entry is not None:
                idx = archive.add(entry)
                self._emit_iteration(
                    "completed",
                    gen,
                    entry.aggregate_score,
                    len(archive),
                    archive_idx=idx,
                )

        return self._build_result(archive, history)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _one_generation(
        self,
        gen: int,
        valset: list[GoldExample[Any, Any]],
        archive: Archive,
    ) -> tuple[ArchiveEntry | None, dict[str, Any]]:
        """One design-reflexion-evaluate cycle.

        Returns ``(entry, history_record)``. ``entry`` is ``None`` when the
        generation was skipped after exhausting debug_max retries.
        """
        archive_view = archive.serialize_for_prompt()
        try:
            design = await self._design_step(archive_view)
        except Exception as exc:  # noqa: BLE001
            logger.warning("meta_agent design step failed at gen {g}: {e}", g=gen, e=exc)
            return None, {
                "generation": gen,
                "skipped": True,
                "reason": f"design_step_failed: {exc}",
            }

        for r in range(self._config.reflexion_passes):
            try:
                design = await self._reflexion_step(design, r)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "meta_agent reflexion pass {r} failed at gen {g}: {e}",
                    r=r, g=gen, e=exc,
                )
                # Reflexion failure isn't fatal — fall through with the
                # last-good design. ADAS does similar: skip the reflexion,
                # try evaluation anyway.
                break

        # Evaluate with debug-retry on hydration failure.
        bundles: list[MetricBundle] | None = None
        for retry in range(self._config.debug_max + 1):
            minibatch = self._sample_minibatch(valset)
            try:
                bundles = await self._evaluator.evaluate_batch(
                    decoded={self._gene.name: design.spec},
                    batch=minibatch,
                )
                # Hydration failures inside evaluator surface as bundles
                # with raw["error"] set; treat per-example all-error as a
                # debug-worthy retry signal.
                if all("error" in b.raw for b in bundles):
                    raise RuntimeError(
                        f"all examples errored: "
                        f"{bundles[0].raw.get('error', 'unknown')}"
                    )
                break
            except (ValidationError, RuntimeError, KeyError, ValueError) as exc:
                if retry >= self._config.debug_max:
                    return None, {
                        "generation": gen,
                        "skipped": True,
                        "reason": f"debug_max_exhausted: {exc}",
                    }
                self._emit_debug_retry(gen, retry, exc)
                try:
                    design = await self._debug_retry_step(design, exc)
                except Exception as inner:  # noqa: BLE001
                    logger.warning(
                        "meta_agent debug retry failed at gen {g}: {e}",
                        g=gen, e=inner,
                    )
                    return None, {
                        "generation": gen,
                        "skipped": True,
                        "reason": f"debug_retry_failed: {inner}",
                    }

        assert bundles is not None
        score = _aggregate(bundles, self._config.weights)
        entry = ArchiveEntry(
            generation=gen,
            spec_json=design.spec.model_dump_json(),
            bundles=bundles,
            aggregate_score=score,
            thought=design.thought,
            parent_idx=_find_parent_idx(archive),
        )
        return entry, {
            "generation": gen,
            "score": score,
            "skipped": False,
            "thought": design.thought[:200],
        }

    async def _design_step(self, archive_view: str) -> TopologyDesign:
        prompt = _build_design_user_prompt(
            gene=self._gene,
            archive_view=archive_view,
            callable_names=self._evaluator._callable_registry.names(),
            agent_names=sorted(self._evaluator._agent_registry.keys()),
            has_factory=self._evaluator._spawn_factory is not None,
        )
        result = await self._meta_agent.run(prompt)
        return result.output

    async def _reflexion_step(
        self, candidate: TopologyDesign, pass_idx: int
    ) -> TopologyDesign:
        prompt = _build_reflexion_user_prompt(
            candidate_design=candidate, pass_idx=pass_idx
        )
        result = await self._meta_agent.run(prompt)
        return result.output

    async def _debug_retry_step(
        self, bad_design: TopologyDesign, error: Exception
    ) -> TopologyDesign:
        prompt = _build_debug_user_prompt(bad_design=bad_design, error=error)
        result = await self._meta_agent.run(prompt)
        return result.output

    def _sample_minibatch(
        self, valset: list[GoldExample[Any, Any]]
    ) -> list[GoldExample[Any, Any]]:
        if len(valset) <= self._config.minibatch_size:
            return valset
        return self._rng.sample(valset, self._config.minibatch_size)

    def _build_result(
        self, archive: Archive, history: list[dict[str, Any]]
    ) -> OptimizationResult:
        best_entry = archive.best()
        best_candidate: dict[str, str] = {self._gene.name: best_entry.spec_json}
        best_decoded = {self._gene.name: self._gene.decode(best_entry.spec_json)}
        pareto_candidates = [
            {self._gene.name: e.spec_json} for e in archive.pareto()
        ]
        return OptimizationResult(
            best_candidate=best_candidate,
            best_decoded=best_decoded,
            best_score=best_entry.aggregate_score,
            pareto_candidates=pareto_candidates,
            history=history,
            raw=archive,
        )

    # --- bus events ---------------------------------------------------

    def _emit_iteration(
        self,
        phase: str,
        generation: int,
        score: float,
        archive_size: int,
        *,
        archive_idx: int | None = None,
    ) -> None:
        if self._bus is None:
            return
        try:
            self._fire(
                self._bus.emit(
                    AgentEvent(
                        event_type="meta_agent.iteration_completed",
                        agent_name="meta_agent_search",
                        data={
                            "phase": phase,
                            "generation": generation,
                            "score": score,
                            "archive_size": archive_size,
                            "archive_idx": archive_idx,
                        },
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("meta_agent iteration emit failed: {e}", e=exc)

    def _emit_debug_retry(
        self, generation: int, retry: int, error: Exception
    ) -> None:
        if self._bus is None:
            return
        try:
            self._fire(
                self._bus.emit(
                    AgentEvent(
                        event_type="meta_agent.debug_retry",
                        agent_name="meta_agent_search",
                        data={
                            "generation": generation,
                            "retry": retry,
                            "error_type": type(error).__name__,
                            "error": str(error)[:300],
                        },
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("meta_agent debug emit failed: {e}", e=exc)

    @staticmethod
    def _fire(coro: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            with contextlib.suppress(Exception):
                asyncio.run(coro)
            return
        loop.create_task(coro)


# --- Helpers ----------------------------------------------------------------


def _aggregate(bundles: list[MetricBundle], weights: MetricWeights) -> float:
    """Mean scalarized score across a batch — the archive ranking key."""
    if not bundles:
        return 0.0
    return sum(b.scalarize(weights) for b in bundles) / len(bundles)


def _find_parent_idx(archive: Archive) -> int | None:
    """Heuristic: best-scored entry is the parent. None if archive is empty."""
    entries = archive.entries
    if not entries:
        return None
    best_idx = max(
        range(len(entries)), key=lambda i: entries[i].aggregate_score
    )
    return best_idx


__all__ = [
    "Archive",
    "ArchiveEntry",
    "ArchiveStrategy",
    "MetaAgentConfig",
    "MetaAgentSearch",
    "TopologyDesign",
]
