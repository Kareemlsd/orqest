"""Serializable IR for Orqest's orchestration primitives.

Closes the gap that an LLM cannot emit a composition topology at runtime because
Pipeline / Parallel / Router / RefinementLoop accept Python callables (conditions,
merges, state-updaters) that have no JSON representation.

This module provides Pydantic v2 models that round-trip cleanly to JSON and
hydrate back to live runtime objects via :mod:`orqest.orchestration.hydrate`.

Design:

* **One discriminated union** (:data:`OperationSpec`) covers every shape that
  can appear in a step position — atomic (`AgentStepSpec` / `FunctionStepSpec`)
  and composite (`PipelineSpec` / `ParallelSpec` / `RouterSpec` /
  `RefinementLoopSpec`). The single union keeps recursion uniform: a Pipeline's
  step list, a Route's step, and a RefinementLoop's step all accept the same
  type.
* **All callables go through name registries.** Conditions, merges, state
  updaters, and FunctionStep functions are referenced by string name; the
  hydrator resolves them against a :class:`CallableRegistry`. Agents are
  referenced either by registry name (string) or inlined as an :class:`AgentSpec`
  for spawn-fresh-per-execution. This is the load-bearing safety property:
  the meta agent's emission surface is *names from an allowlist*, never code.
* **TopologySpec** is the narrower top-level union (composites only) — used
  by :class:`TopologyGene` to type the genome's seed.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orqest.autonomy.spec import AgentSpec


class StepConfigSpec(BaseModel):
    """Per-step error-handling config used inside :class:`PipelineSpec`.

    Mirrors :class:`orqest.orchestration.types.StepConfig` but with a string
    ``on_error`` literal instead of the runtime ``ErrorStrategy`` Enum (so it
    serializes cleanly to JSON).
    """

    model_config = ConfigDict(frozen=True)

    name: str = ""
    on_error: Literal["stop", "skip", "retry"] = "stop"
    max_retries: int = 1


class AgentStepSpec(BaseModel):
    """An atomic step that wraps a single :class:`BaseAgent`.

    The agent is resolved by ``agent_name`` against the hydrator's agent
    registry, OR constructed fresh from ``inline_spec`` (an :class:`AgentSpec`).
    Exactly one of the two must be present — the validator enforces this.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["agent_step"] = "agent_step"
    agent_name: str | None = None
    """Lookup key in the agent_registry. Mutually exclusive with ``inline_spec``."""

    inline_spec: AgentSpec | None = None
    """When set, the agent is spawned fresh from this spec via
    :class:`AgentFactory`. Mutually exclusive with ``agent_name``."""

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "AgentStepSpec":
        if (self.agent_name is None) == (self.inline_spec is None):
            raise ValueError(
                "AgentStepSpec requires exactly one of "
                "{agent_name, inline_spec}; both or neither is invalid."
            )
        return self


class FunctionStepSpec(BaseModel):
    """An atomic step that wraps a registered async callable."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["function_step"] = "function_step"
    callable_name: str
    """Lookup key in the callable_registry. The hydrator resolves this name
    to a callable; unknown names raise :class:`KeyError` at hydration time."""

    name: str | None = None
    """Optional display name. Falls back to ``callable_name``."""


class PipelineStepEntry(BaseModel):
    """One entry inside a :class:`PipelineSpec`'s ``steps`` list.

    Wraps an :data:`OperationSpec` with optional per-step :class:`StepConfigSpec`.
    Keeping the entry shape uniform makes JSON emission predictable for the
    meta agent (no mixed-list-shape footgun).
    """

    model_config = ConfigDict(frozen=True)

    operation: "OperationSpec"
    config: StepConfigSpec | None = None


class PipelineSpec(BaseModel):
    """Sequential composition: each entry's output feeds the next entry's input.

    Hydrates to :class:`orqest.orchestration.pipeline.Pipeline`.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["pipeline"] = "pipeline"
    steps: list[PipelineStepEntry] = Field(min_length=1)
    """At least one step is required. Empty pipelines raise at hydration
    (mirroring :class:`Pipeline`'s own ValueError)."""

    name: str = "pipeline"


class ParallelSpec(BaseModel):
    """Concurrent composition: all entries run on input_data, results merge.

    Hydrates to :class:`orqest.orchestration.parallel.Parallel`.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["parallel"] = "parallel"
    steps: list["OperationSpec"] = Field(min_length=1)

    merge: str = "collect_all"
    """Merge strategy name. ``"collect_all"`` and ``"first_wins"`` resolve to
    :class:`orqest.orchestration.parallel.MergeStrategy` built-ins; any other
    value is looked up in the hydrator's callable_registry."""

    timeout: float | None = None
    """Wall-clock timeout in seconds. ``None`` means no limit."""

    name: str = "parallel"


class RouteSpec(BaseModel):
    """One named branch in a :class:`RouterSpec`.

    The ``step`` may be an atomic (AgentStep / FunctionStep) or another nested
    topology — the hydrator wraps composite operations in a Step adapter so
    they conform to the :class:`Step` protocol.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    step: "OperationSpec"
    condition_name: str | None = None
    """Registered predicate name; ``None`` makes this route classifier-only.

    The :class:`RouterSpec` itself enforces: at least one route must have
    a condition_name OR a classifier must be set."""


class RouterSpec(BaseModel):
    """Dispatch input to one of N routes via classifier or rule conditions.

    Hydrates to :class:`orqest.orchestration.router.Router`.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["router"] = "router"
    routes: list[RouteSpec] = Field(min_length=1)
    classifier: AgentSpec | str | None = None
    """Optional classifier. ``str`` is an agent_registry lookup; an
    :class:`AgentSpec` spawns fresh. The :class:`Router` constructor requires
    EITHER a classifier OR at least one route with a condition — the hydrator
    surfaces the underlying ``ValueError`` if neither is present."""

    fallback_step: "OperationSpec | None" = None
    """Step to run when no route matches. ``None`` raises ``RouterError`` on
    no-match."""

    name: str = "router"


class RefinementLoopSpec(BaseModel):
    """Iterate a step with evaluator feedback until convergence or limits.

    Hydrates to :class:`orqest.orchestration.loop.RefinementLoop`.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["refinement_loop"] = "refinement_loop"
    step: "OperationSpec"

    evaluator: AgentSpec | str
    """Required evaluator. ``str`` is an agent_registry name (the agent must
    return an :class:`EvalResult`-shaped output); an :class:`AgentSpec` spawns
    fresh. A pure-callable evaluator is also accepted via the registry — pass
    its name as the ``str`` and have it resolve via the agent_registry's
    callable-fallback (or use a tiny BaseAgent wrapper around it)."""

    state_updater_name: str
    """Required callable_registry name for the
    ``(current_input, output, eval_result) -> next_input`` updater."""

    max_iterations: int = 5
    timeout: float | None = None
    convergence_window: int | None = None
    convergence_threshold: float = 0.01
    confidence_threshold: float | None = None
    name: str = "refinement_loop"


# --- Discriminated unions ---------------------------------------------------

OperationSpec = Annotated[
    "AgentStepSpec | FunctionStepSpec | PipelineSpec | ParallelSpec "
    "| RouterSpec | RefinementLoopSpec",
    Field(discriminator="kind"),
]
"""Any composable operation. Both atomic (AgentStep / FunctionStep) and
composite (Pipeline / Parallel / Router / RefinementLoop) shapes share this
union so recursion is uniform: a Pipeline's step entry, a Route's step,
and a RefinementLoop's step all accept ``OperationSpec``.

The string-form annotation defers Pydantic's discriminator resolution until
all four composite classes are defined (forward references)."""

TopologySpec = Annotated[
    PipelineSpec | ParallelSpec | RouterSpec | RefinementLoopSpec,
    Field(discriminator="kind"),
]
"""The narrower top-level union — composite topologies only. Used by
:class:`TopologyGene` to type the genome seed: a meta-agent-emitted candidate
must be one of the four composite shapes (an atomic AgentStep alone is not
a "topology" worth evolving)."""


# Resolve forward references after every member of OperationSpec exists.
PipelineStepEntry.model_rebuild()
PipelineSpec.model_rebuild()
ParallelSpec.model_rebuild()
RouteSpec.model_rebuild()
RouterSpec.model_rebuild()
RefinementLoopSpec.model_rebuild()


__all__ = [
    "AgentStepSpec",
    "FunctionStepSpec",
    "OperationSpec",
    "ParallelSpec",
    "PipelineSpec",
    "PipelineStepEntry",
    "RefinementLoopSpec",
    "RouteSpec",
    "RouterSpec",
    "StepConfigSpec",
    "TopologySpec",
]
