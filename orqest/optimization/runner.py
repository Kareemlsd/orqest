"""High-level entry point that drives ``gepa.optimize()`` end-to-end.

The runner takes:

* an :class:`OptimizationConfig` (the policy knobs)
* a :class:`Genome` (what's evolvable)
* an :class:`Evaluator` (how to score)
* a trainset of :class:`GoldExample`s (and optionally a held-out valset)

…and returns an :class:`OptimizationResult` carrying the best candidate,
the Pareto frontier, the run history, and the raw GEPA result for any
escape-hatch needs.

The runner enforces three Orqest-side invariants on top of GEPA's API:

* **Reproducibility.** When no explicit valset is provided, the trainset
  is split deterministically using ``config.seed`` + ``config.valset_fraction``.
* **Gene-kind gating.** :class:`ScalarGene` / :class:`CategoricalGene`
  evolution is gated by ``config.enable_*`` flags; a gated gene appearing
  in the genome raises :class:`NotImplementedError` with a clear message.
* **Optional dependency surfacing.** All ``gepa`` imports go through
  ``orqest.optimization._compat``; the runner raises a friendly error if
  the optional dep is missing.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from typing import Any

from orqest.observability.events import EventBus
from orqest.optimization._compat import optimize as _gepa_optimize
from orqest.optimization.adapter import OrqestGEPAAdapter
from orqest.optimization.config import OptimizationConfig
from orqest.optimization.evaluator import Evaluator, GoldExample
from orqest.optimization.genome import Genome


def _to_litellm_model_string(model: str | None) -> str | None:
    """Translate Orqest's ``provider:model`` to litellm's ``provider/model``.

    Orqest follows pydantic-ai's convention (``"openai:gpt-4.1"``) but
    GEPA's default ``reflection_lm`` path imports litellm, which insists on
    ``"openai/gpt-4.1"`` (or a bare model name it can auto-detect). The
    transform is a single ``:`` -> ``/`` replacement on the first
    occurrence; bare model names and already-slashed strings pass through.

    Returns ``None`` for ``None`` so the GEPA default kicks in.
    """
    if model is None or ":" not in model:
        return model
    provider, _, rest = model.partition(":")
    return f"{provider}/{rest}"


# Map an Orqest model-string provider prefix to the env var litellm reads.
# Used as a defensive fallback only — the primary api_key path is the
# explicit-callable mode in `_make_reflection_lm`.
_PROVIDER_ENV_VAR: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _ensure_litellm_api_key(model: str | None, api_key: str | None) -> None:
    """Defensive env-var setdefault — secondary to :func:`_make_reflection_lm`.

    The primary api_key path is the explicit callable built by
    :func:`_make_reflection_lm`, which bypasses env vars entirely. This
    helper still runs as a belt-and-suspenders safety net in case GEPA
    internals reach for env vars elsewhere; ``setdefault`` ensures we
    never clobber an explicit user-set key.
    """
    if not api_key or not model:
        return
    provider = model.split(":", 1)[0].split("/", 1)[0].split("-", 1)[0]
    env_var = _PROVIDER_ENV_VAR.get(provider)
    if env_var is not None:
        os.environ.setdefault(env_var, api_key)


def _make_reflection_lm(
    model: str | None, api_key: str | None
) -> "Any | None":
    """Build a GEPA ``reflection_lm`` callable that explicitly passes the
    ``api_key`` to ``litellm.completion`` — no env-var dependency.

    Returns ``None`` when either ``model`` or ``api_key`` is missing, so
    GEPA falls back to its built-in string-mode wrapper (which reads env
    vars). The callable signature matches GEPA's ``LanguageModel``
    protocol: takes a ``str`` (or list of message dicts) and returns the
    generated ``str`` content.

    The model string is litellm-formatted (slash-style) since this
    callable lives below the format-translation boundary.
    """
    if not model or not api_key:
        return None

    litellm_model = _to_litellm_model_string(model)
    if litellm_model is None:
        return None

    def _lm(prompt: "str | list[dict[str, str]]") -> str:
        # Late-import litellm so module load doesn't require gepa[full].
        import litellm  # type: ignore[import-not-found]

        messages = (
            prompt
            if isinstance(prompt, list)
            else [{"role": "user", "content": prompt}]
        )
        response = litellm.completion(
            model=litellm_model,
            messages=messages,
            api_key=api_key,
        )
        return response.choices[0].message.content or ""

    return _lm


@dataclass(frozen=True)
class OptimizationResult:
    """Immutable summary of a completed optimization run."""

    best_candidate: dict[str, str]
    """The winning candidate (per GEPA's ``best_idx`` aggregate score)."""

    best_decoded: dict[str, Any]
    """:meth:`Genome.decode` applied to ``best_candidate``."""

    best_score: float
    """The best candidate's aggregate validation score."""

    pareto_candidates: list[dict[str, str]]
    """Distinct candidates appearing on GEPA's instance-level Pareto front
    (``per_val_instance_best_candidates``). Inspect for tradeoffs the
    aggregate winner doesn't surface."""

    history: list[dict[str, Any]] = field(default_factory=list)
    """Per-iteration summary (iteration index, mean score, mean accuracy)
    captured from the bus during the run, when a bus was provided."""

    raw: Any = None
    """The original :class:`gepa.core.result.GEPAResult` — escape hatch
    for advanced inspection (lineage, val_subscores, per_objective_*)."""


class OptimizationRunner:
    """Drive ``gepa.optimize()`` against an Orqest :class:`Evaluator`."""

    def __init__(
        self,
        config: OptimizationConfig,
        *,
        genome: Genome,
        evaluator: Evaluator[Any, Any],
        bus: EventBus | None = None,
        api_key: str | None = None,
    ) -> None:
        """Wire the optimizer.

        Args:
            config: Frozen :class:`OptimizationConfig` (rollout budget,
                reflection model, weights, etc.).
            genome: The mutable surface — list of typed genes.
            evaluator: Wraps the user's ``agent_factory`` + ``score_fn``
                and produces :class:`MetricBundle`s per example.
            bus: Optional :class:`EventBus` for ``optimization.iteration_completed``
                events; when set, history is collected into the result.
            api_key: Optional API key for the *reflection* model. Bridged
                to litellm's expected provider env var (``OPENAI_API_KEY``,
                ``ANTHROPIC_API_KEY``, ...) via ``os.environ.setdefault``
                — pre-existing env vars always win. Required when GEPA's
                default reflection path is used and no env var is set;
                ignored when irrelevant.
        """
        self._config = config
        self._genome = genome
        self._evaluator = evaluator
        self._bus = bus
        self._api_key = api_key
        self._validate_genome()

    def _validate_genome(self) -> None:
        kinds = self._genome.gene_kinds()
        if "scalar" in kinds and not self._config.enable_scalar_genes:
            raise NotImplementedError(
                "Genome contains ScalarGene but enable_scalar_genes is False. "
                "Set OptimizationConfig(enable_scalar_genes=True) to opt in. "
                "Note: scalar gene evolution is gated until the upstream "
                "scalar/categorical decoding loop ships in W1.1+."
            )
        if "categorical" in kinds and not self._config.enable_categorical_genes:
            raise NotImplementedError(
                "Genome contains CategoricalGene but enable_categorical_genes "
                "is False. Set OptimizationConfig(enable_categorical_genes=True) "
                "to opt in."
            )

    async def optimize(
        self,
        trainset: list[GoldExample[Any, Any]],
        valset: list[GoldExample[Any, Any]] | None = None,
    ) -> OptimizationResult:
        """Run GEPA against the given gold sets.

        When ``valset`` is None, splits ``trainset`` deterministically using
        ``config.seed`` and ``config.valset_fraction``.
        """
        if valset is None:
            trainset, valset = self._split(trainset)

        adapter = OrqestGEPAAdapter(
            self._genome,
            self._evaluator,
            self._config.weights,
            bus=self._bus,
            emit_per_example_events=self._config.emit_per_example_events,
        )

        history = self._wire_history_collector()

        # Belt-and-suspenders env-var setdefault for any internal GEPA
        # path we don't directly intercept. Primary api_key delivery
        # happens via the explicit callable below.
        _ensure_litellm_api_key(self._config.reflection_model, self._api_key)

        # Build the reflection LM as an explicit callable when we have an
        # api_key — bypasses env vars entirely. Falls back to the
        # litellm-formatted string when no api_key is provided (GEPA then
        # builds its own internal callable that reads env vars).
        reflection_lm: Any = _make_reflection_lm(
            self._config.reflection_model, self._api_key
        )
        if reflection_lm is None:
            reflection_lm = _to_litellm_model_string(self._config.reflection_model)

        seed = self._genome.to_seed()
        gepa_result = _gepa_optimize(
            seed_candidate=seed,
            trainset=trainset,
            valset=valset,
            adapter=adapter,
            # No task_lm / evaluator here: the adapter owns both. GEPA's
            # api.py asserts task_lm is None when an adapter is provided,
            # because the user's agent_factory (inside the adapter's
            # Evaluator) is what actually calls the task model.
            reflection_lm=reflection_lm,
            max_metric_calls=self._config.max_metric_calls,
            frontier_type=self._config.frontier_type,
            cache_evaluation=self._config.cache_evaluations,
            seed=self._config.seed if self._config.seed is not None else 0,
            display_progress_bar=False,
            raise_on_exception=False,
        )

        best_idx = gepa_result.best_idx
        best_candidate: dict[str, str] = gepa_result.candidates[best_idx]
        best_decoded = self._genome.decode(best_candidate)
        best_score = float(gepa_result.val_aggregate_scores[best_idx])

        pareto_candidates = self._extract_pareto(gepa_result)

        return OptimizationResult(
            best_candidate=best_candidate,
            best_decoded=best_decoded,
            best_score=best_score,
            pareto_candidates=pareto_candidates,
            history=history,
            raw=gepa_result,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _split(
        self, trainset: list[GoldExample[Any, Any]]
    ) -> tuple[list[GoldExample[Any, Any]], list[GoldExample[Any, Any]]]:
        if len(trainset) < 2:
            raise ValueError(
                "Need at least 2 examples to split into trainset + valset; "
                "pass an explicit valset for tiny gold sets."
            )
        rng = random.Random(self._config.seed)
        indices = list(range(len(trainset)))
        rng.shuffle(indices)
        n_val = max(1, int(round(len(indices) * self._config.valset_fraction)))
        val_idx = set(indices[:n_val])
        train = [ex for i, ex in enumerate(trainset) if i not in val_idx]
        val = [ex for i, ex in enumerate(trainset) if i in val_idx]
        return train, val

    def _wire_history_collector(self) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        if self._bus is None:
            return history

        def collect(event: Any) -> None:
            history.append(dict(event.data))

        self._bus.subscribe("optimization.iteration_completed", collect)
        return history

    @staticmethod
    def _extract_pareto(gepa_result: Any) -> list[dict[str, str]]:
        """Distinct candidates on the per-instance Pareto front."""
        try:
            seen: set[int] = set()
            for indices in gepa_result.per_val_instance_best_candidates.values():
                seen.update(indices)
            return [gepa_result.candidates[i] for i in sorted(seen)]
        except Exception:  # noqa: BLE001
            return [gepa_result.candidates[gepa_result.best_idx]]
