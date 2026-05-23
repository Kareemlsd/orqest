"""Hydrate :mod:`orqest.orchestration.spec` Pydantic models into runtime objects.

The spec layer is the canonical *serialization surface*; this module owns the
*deserialization* side. Two responsibilities:

1. :class:`CallableRegistry` — a name→callable allowlist. The meta-agent emits
   names from this registry's keys; the hydrator looks them up here. **No
   ``eval`` / ``exec`` ever runs** — the security perimeter is "names from a
   user-controlled allowlist," nothing more.
2. :func:`topology_from_spec` — dispatches on ``spec.kind`` and recursively
   builds a live Pipeline / Parallel / Router / RefinementLoop. Nested
   composites (a Pipeline inside a Route, a Parallel inside a RefinementLoop)
   are wrapped in :class:`_TopologyAsStep` so they conform to the
   :class:`Step` protocol the runtime classes expect.

Agents are resolved two ways:

* By **name** against ``agent_registry`` — a ``dict[str, Callable[[], BaseAgent]]``
  of factories (not instances). Factories match the existing pattern used by
  :class:`Evaluator.agent_factory` and avoid cached-``_agent`` problems when the
  same logical agent is instantiated multiple times across a search.
* By **inline** :class:`AgentSpec` — spawned fresh via :class:`AgentFactory`.
  Requires a factory to be provided to the hydrator.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orqest.agents.base_agent import BaseAgent
from orqest.autonomy.factory import AgentFactory
from orqest.orchestration.loop import LoopResult, RefinementLoop
from orqest.orchestration.parallel import MergeStrategy, Parallel, ParallelResult
from orqest.orchestration.pipeline import Pipeline
from orqest.orchestration.router import Route, Router
from orqest.orchestration.spec import (
    AgentStepSpec,
    FunctionStepSpec,
    OperationSpec,
    ParallelSpec,
    PipelineSpec,
    RefinementLoopSpec,
    RouterSpec,
    StepConfigSpec,
    TopologySpec,
)
from orqest.orchestration.step import AgentStep, FunctionStep, Step
from orqest.orchestration.types import ErrorStrategy, StepConfig

_BUILTIN_MERGES: dict[str, Callable[[list[Any]], Any]] = {
    "collect_all": MergeStrategy.collect_all,
    "first_wins": MergeStrategy.first_wins,
}


class CallableRegistry:
    """Name → callable map. Explicit, no introspection magic.

    The meta agent's design step receives ``registry.names()`` as its allowed
    vocabulary; any name it emits MUST be in here, or hydration raises
    :class:`KeyError`. This is the load-bearing security property of the W3.A
    layer: there is no eval, no exec, no name forgery — the registry holds
    the actual callables, the meta agent can only refer to them by name.
    """

    def __init__(self) -> None:
        self._fns: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """Register *fn* under *name*. Re-registering replaces silently."""
        if not isinstance(name, str) or not name:
            raise ValueError("CallableRegistry name must be a non-empty string")
        if not callable(fn):
            raise TypeError(f"CallableRegistry value for {name!r} must be callable")
        self._fns[name] = fn

    def get(self, name: str) -> Callable[..., Any]:
        """Look up *name*. Raises :class:`KeyError` with all known names on miss."""
        try:
            return self._fns[name]
        except KeyError as exc:
            raise KeyError(
                f"CallableRegistry has no entry for {name!r}; "
                f"known names: {sorted(self._fns.keys())}"
            ) from exc

    def names(self) -> list[str]:
        """All registered names, sorted — surface for the meta-agent prompt."""
        return sorted(self._fns.keys())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._fns

    def __len__(self) -> int:
        return len(self._fns)


# --- Step-adapter for nested composite topologies ---------------------------


class _TopologyAsStep:
    """Wrap a Pipeline / Parallel / Router / RefinementLoop as a :class:`Step`.

    Necessary because the runtime composite classes use ``.run()`` (returning
    rich result objects) while the :class:`Step` protocol the runtime expects
    is ``.execute()`` returning a bare value.

    The wrapper unpacks composite results to their meaningful payload:

    * :class:`Pipeline` / :class:`Router` → identity (their ``.run()`` already
      returns the final/route output directly).
    * :class:`Parallel` → ``ParallelResult.merged`` (the merge-strategy output).
    * :class:`RefinementLoop` → ``LoopResult.output`` (the converged value).
    """

    def __init__(self, topology: Any, *, name: str) -> None:
        self._topology = topology
        self._name = name

    @property
    def step_name(self) -> str:
        return self._name

    async def execute(self, input_data: Any) -> Any:
        result = await self._topology.run(input_data)
        if isinstance(result, ParallelResult):
            return result.merged
        if isinstance(result, LoopResult):
            return result.output
        return result


# --- Hydration --------------------------------------------------------------


def _resolve_agent(
    *,
    agent_name: str | None,
    inline_spec: Any,
    agent_registry: dict[str, Callable[[], BaseAgent]],
    agent_factory: AgentFactory | None,
) -> BaseAgent:
    """Resolve an agent reference (name or inline spec) to a fresh BaseAgent."""
    if agent_name is not None:
        try:
            factory = agent_registry[agent_name]
        except KeyError as exc:
            raise KeyError(
                f"agent_registry has no entry for {agent_name!r}; "
                f"known names: {sorted(agent_registry.keys())}"
            ) from exc
        return factory()
    # inline_spec path
    if agent_factory is None:
        raise ValueError(
            "AgentStepSpec.inline_spec requires an AgentFactory passed to "
            "topology_from_spec(agent_factory=...). None was provided."
        )
    return agent_factory.spawn(inline_spec)


def _hydrate_operation_as_step(
    op: Any,
    *,
    callable_registry: CallableRegistry,
    agent_registry: dict[str, Callable[[], BaseAgent]],
    agent_factory: AgentFactory | None,
) -> Step:
    """Turn any :data:`OperationSpec` into a Step-conformant object.

    Atomic (AgentStep / FunctionStep) hydrate to their direct Step wrappers;
    composite (Pipeline / Parallel / Router / RefinementLoop) hydrate to a
    runtime instance wrapped in :class:`_TopologyAsStep`.
    """
    if isinstance(op, AgentStepSpec):
        agent = _resolve_agent(
            agent_name=op.agent_name,
            inline_spec=op.inline_spec,
            agent_registry=agent_registry,
            agent_factory=agent_factory,
        )
        return AgentStep(agent)

    if isinstance(op, FunctionStepSpec):
        fn = callable_registry.get(op.callable_name)
        return FunctionStep(fn, name=op.name or op.callable_name)

    # Composite — recurse, wrap as Step.
    runtime = topology_from_spec(
        op,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
        agent_factory=agent_factory,
    )
    return _TopologyAsStep(runtime, name=getattr(op, "name", op.kind))


def _to_step_config(cfg: StepConfigSpec | None) -> StepConfig | None:
    """Translate the JSON-friendly StepConfigSpec to the runtime StepConfig."""
    if cfg is None:
        return None
    return StepConfig(
        name=cfg.name,
        on_error=ErrorStrategy(cfg.on_error),
        max_retries=cfg.max_retries,
    )


def pipeline_from_spec(
    spec: PipelineSpec,
    *,
    callable_registry: CallableRegistry,
    agent_registry: dict[str, Callable[[], BaseAgent]],
    agent_factory: AgentFactory | None = None,
) -> Pipeline:
    """Hydrate a :class:`PipelineSpec` into a live :class:`Pipeline`."""
    entries: list[Any] = []
    for entry in spec.steps:
        step = _hydrate_operation_as_step(
            entry.operation,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            agent_factory=agent_factory,
        )
        cfg = _to_step_config(entry.config)
        if cfg is None:
            entries.append(step)
        else:
            entries.append((step, cfg))
    return Pipeline(entries, name=spec.name)


def parallel_from_spec(
    spec: ParallelSpec,
    *,
    callable_registry: CallableRegistry,
    agent_registry: dict[str, Callable[[], BaseAgent]],
    agent_factory: AgentFactory | None = None,
) -> Parallel:
    """Hydrate a :class:`ParallelSpec` into a live :class:`Parallel`."""
    steps = [
        _hydrate_operation_as_step(
            op,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            agent_factory=agent_factory,
        )
        for op in spec.steps
    ]
    merge_fn = _BUILTIN_MERGES.get(spec.merge)
    if merge_fn is None:
        merge_fn = callable_registry.get(spec.merge)
    return Parallel(
        steps,
        merge=merge_fn,
        timeout=spec.timeout,
        name=spec.name,
    )


def router_from_spec(
    spec: RouterSpec,
    *,
    callable_registry: CallableRegistry,
    agent_registry: dict[str, Callable[[], BaseAgent]],
    agent_factory: AgentFactory | None = None,
) -> Router:
    """Hydrate a :class:`RouterSpec` into a live :class:`Router`."""
    routes: list[Route] = []
    for r in spec.routes:
        step = _hydrate_operation_as_step(
            r.step,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            agent_factory=agent_factory,
        )
        condition = (
            callable_registry.get(r.condition_name)
            if r.condition_name is not None
            else None
        )
        routes.append(Route(name=r.name, step=step, condition=condition))

    classifier: BaseAgent | Callable[..., Any] | None = None
    if isinstance(spec.classifier, str):
        # str = agent_registry name OR callable_registry name (try agent first)
        if spec.classifier in agent_registry:
            classifier = agent_registry[spec.classifier]()
        else:
            classifier = callable_registry.get(spec.classifier)
    elif spec.classifier is not None:
        # Inline AgentSpec
        classifier = _resolve_agent(
            agent_name=None,
            inline_spec=spec.classifier,
            agent_registry=agent_registry,
            agent_factory=agent_factory,
        )

    fallback: Step | None = None
    if spec.fallback_step is not None:
        fallback = _hydrate_operation_as_step(
            spec.fallback_step,
            callable_registry=callable_registry,
            agent_registry=agent_registry,
            agent_factory=agent_factory,
        )

    return Router(
        routes,
        classifier=classifier,
        fallback=fallback,
        name=spec.name,
    )


def refinement_loop_from_spec(
    spec: RefinementLoopSpec,
    *,
    callable_registry: CallableRegistry,
    agent_registry: dict[str, Callable[[], BaseAgent]],
    agent_factory: AgentFactory | None = None,
) -> RefinementLoop:
    """Hydrate a :class:`RefinementLoopSpec` into a live :class:`RefinementLoop`."""
    step = _hydrate_operation_as_step(
        spec.step,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
        agent_factory=agent_factory,
    )

    if isinstance(spec.evaluator, str):
        if spec.evaluator in agent_registry:
            evaluator: Any = agent_registry[spec.evaluator]()
        else:
            evaluator = callable_registry.get(spec.evaluator)
    else:
        evaluator = _resolve_agent(
            agent_name=None,
            inline_spec=spec.evaluator,
            agent_registry=agent_registry,
            agent_factory=agent_factory,
        )

    state_updater = callable_registry.get(spec.state_updater_name)

    return RefinementLoop(
        step,
        evaluator,
        state_updater=state_updater,
        max_iterations=spec.max_iterations,
        timeout=spec.timeout,
        convergence_window=spec.convergence_window,
        convergence_threshold=spec.convergence_threshold,
        confidence_threshold=spec.confidence_threshold,
    )


_HYDRATORS = {
    "pipeline": pipeline_from_spec,
    "parallel": parallel_from_spec,
    "router": router_from_spec,
    "refinement_loop": refinement_loop_from_spec,
}


def topology_from_spec(
    spec: TopologySpec,
    *,
    callable_registry: CallableRegistry,
    agent_registry: dict[str, Callable[[], BaseAgent]],
    agent_factory: AgentFactory | None = None,
) -> Pipeline | Parallel | Router | RefinementLoop:
    """Dispatch on ``spec.kind`` and hydrate to the right runtime class.

    Recursive: nested composites inside step positions are hydrated and
    wrapped via :class:`_TopologyAsStep` so the parent runtime sees a Step.
    """
    hydrator = _HYDRATORS.get(spec.kind)
    if hydrator is None:
        raise ValueError(
            f"topology_from_spec: unknown topology kind {spec.kind!r}; "
            f"expected one of {sorted(_HYDRATORS.keys())}"
        )
    return hydrator(  # type: ignore[no-any-return]
        spec,
        callable_registry=callable_registry,
        agent_registry=agent_registry,
        agent_factory=agent_factory,
    )


def _count_agent_steps(spec: OperationSpec) -> int:
    """Recursive structural metric: total :class:`AgentStepSpec` count.

    Used by :class:`TopologyEvaluator` to fill ``MetricBundle.raw["n_agents"]``
    — a proxy for cost ceiling in topology Pareto frontiers.
    """
    if isinstance(spec, AgentStepSpec):
        return 1
    if isinstance(spec, FunctionStepSpec):
        return 0
    if isinstance(spec, PipelineSpec):
        return sum(_count_agent_steps(e.operation) for e in spec.steps)
    if isinstance(spec, ParallelSpec):
        return sum(_count_agent_steps(s) for s in spec.steps)
    if isinstance(spec, RouterSpec):
        n = sum(_count_agent_steps(r.step) for r in spec.routes)
        if isinstance(spec.classifier, str) and spec.classifier:
            n += 1  # classifier is an agent (or callable; conservative)
        elif spec.classifier is not None:
            n += 1
        if spec.fallback_step is not None:
            n += _count_agent_steps(spec.fallback_step)
        return n
    if isinstance(spec, RefinementLoopSpec):
        n = _count_agent_steps(spec.step)
        if isinstance(spec.evaluator, str) and spec.evaluator:
            n += 1
        elif spec.evaluator is not None:
            n += 1
        return n
    return 0


def _topology_depth(spec: OperationSpec) -> int:
    """Recursive structural metric: max nesting depth.

    Atomic steps are depth 0; a Pipeline of two atomic steps is depth 1; a
    Pipeline whose entry is another Pipeline is depth 2; etc. Used by
    :class:`TopologyEvaluator` to fill ``MetricBundle.raw["depth"]`` — a proxy
    for latency ceiling.
    """
    if isinstance(spec, (AgentStepSpec, FunctionStepSpec)):
        return 0
    if isinstance(spec, PipelineSpec):
        children = [_topology_depth(e.operation) for e in spec.steps]
        return 1 + max(children, default=0)
    if isinstance(spec, ParallelSpec):
        return 1 + max((_topology_depth(s) for s in spec.steps), default=0)
    if isinstance(spec, RouterSpec):
        children = [_topology_depth(r.step) for r in spec.routes]
        if spec.fallback_step is not None:
            children.append(_topology_depth(spec.fallback_step))
        return 1 + max(children, default=0)
    if isinstance(spec, RefinementLoopSpec):
        return 1 + _topology_depth(spec.step)
    return 0


__all__ = [
    "CallableRegistry",
    "parallel_from_spec",
    "pipeline_from_spec",
    "refinement_loop_from_spec",
    "router_from_spec",
    "topology_from_spec",
]
