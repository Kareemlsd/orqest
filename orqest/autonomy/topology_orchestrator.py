"""Runtime topology design + execution — the topology counterpart to MetaOrchestrator.

Where :class:`MetaOrchestrator` decomposes a goal into a flat sequential
``TaskDecomposition`` and executes the subtasks one-by-one,
:class:`TopologyOrchestrator` asks a designer to emit a typed
:data:`TopologySpec` (Pipeline / Parallel / Router / RefinementLoop) for
*this* request, hydrates it via :func:`topology_from_spec`, runs it, and
records the outcome to the designer's cache (which is how online learning
over "what topology works for what kind of goal" happens).

Both orchestrators ship; they serve different runtime postures:

* :class:`MetaOrchestrator` for flat sequential decomposition — cheaper,
  ExecutionPlan-shaped, stable.
* :class:`TopologyOrchestrator` for full-topology design — richer (branching,
  parallelism, refinement loops), more expensive per request, with cache-
  amortized learning.
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from orqest.agents.base_agent import BaseAgent
from orqest.autonomy.factory import AgentFactory
from orqest.observability.events import AgentEvent, EventBus
from orqest.autonomy.runtime import RuntimeTopologyDesigner
from orqest.optimization.topology import unpack_topology_output
from orqest.orchestration.hydrate import (
    CallableRegistry,
    _count_agent_steps,
    _topology_depth,
    topology_from_spec,
)


class TopologyExecutionResult(BaseModel):
    """Outcome of one :meth:`TopologyOrchestrator.execute` call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    goal: str
    success: bool
    output: Any = None
    error: str | None = None

    spec_kind: str
    """``'pipeline'`` / ``'parallel'`` / ``'router'`` / ``'refinement_loop'``."""

    cache_hit: bool
    """``True`` when the designed spec came from the cache; ``False`` for
    fresh designs (including stale-cache fall-throughs)."""

    n_agents: int = Field(ge=0)
    """Mirrors :class:`TopologyEvaluator`'s structural metric."""

    depth: int = Field(ge=0)
    """Maximum nesting depth of the executed topology."""

    design_ms: float = Field(ge=0.0)
    """Time spent in the designer (cache lookup + LLM call). ~0 on cache hit."""

    execution_ms: float = Field(ge=0.0)
    """Time spent in :meth:`Pipeline.run` (or equivalent)."""

    total_ms: float = Field(ge=0.0)
    """End-to-end wall-clock for the full :meth:`execute` call."""


class TopologyOrchestrator:
    """Per-request topology design + execution loop.

    Mirrors :class:`MetaOrchestrator`'s constructor pattern so consumers can
    swap one for the other when they want richer topology synthesis.

    Lifecycle of one :meth:`execute` call:

    1. Designer is asked for a :data:`TopologySpec` for the goal (cache hit
       short-circuits the LLM call).
    2. Spec is hydrated via :func:`topology_from_spec` against the
       configured registries.
    3. Topology is run; the result is unpacked
       (:class:`ParallelResult.merged` / :class:`LoopResult.output` /
       passthrough).
    4. Outcome is recorded to the designer's cache (success → store /
       refresh; failure → reliability decay).
    5. Bus event ``topology.execution_completed`` (or
       ``topology.execution_failed``) is emitted.
    """

    def __init__(
        self,
        designer: RuntimeTopologyDesigner,
        *,
        callable_registry: CallableRegistry,
        agent_registry: dict[str, Callable[[], BaseAgent[Any, Any]]],
        agent_factory: AgentFactory | None = None,
        bus: EventBus | None = None,
    ) -> None:
        """Wire the orchestrator.

        Args:
            designer: A configured :class:`RuntimeTopologyDesigner`. The
                designer carries the cache, seed library, fallback spec,
                etc.; the orchestrator's job is purely the execution wrap.
            callable_registry: Allowlist of named callables for hydration.
                Typically the same instance the designer was constructed
                with (the designer needs it for *prompt* construction; the
                orchestrator needs it for *runtime* hydration).
            agent_registry: Map from agent name to factory.
            agent_factory: Optional :class:`AgentFactory` for hydrating
                inline AgentSpec references in proposed topologies.
            bus: Optional :class:`EventBus` for ``topology.execution_*``
                events.

        """
        self._designer = designer
        self._callable_registry = callable_registry
        self._agent_registry = agent_registry
        self._agent_factory = agent_factory
        self._bus = bus

    @property
    def designer(self) -> RuntimeTopologyDesigner:
        return self._designer

    async def execute(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> TopologyExecutionResult:
        """Design → hydrate → run → record. See class docstring for the flow.

        Returns a :class:`TopologyExecutionResult`. On execution exception,
        the result is built with ``success=False`` and re-raised — the
        caller decides whether to retry / fall back / surface to the user.
        Cache failure-recording happens before re-raise so reliability
        decay always fires.
        """
        t0 = monotonic()

        # Capture cache-hit signal by snapshotting designer.stats before/after.
        hits_before = self._designer.stats.hits
        spec = await self._designer.design(goal, context=context)
        cache_hit = self._designer.stats.hits > hits_before
        t_designed = monotonic()

        n_agents = _count_agent_steps(spec)
        depth = _topology_depth(spec)

        try:
            topology = topology_from_spec(
                spec,
                callable_registry=self._callable_registry,
                agent_registry=self._agent_registry,
                agent_factory=self._agent_factory,
            )
            run_result = await topology.run(goal)
            output = unpack_topology_output(run_result)
        except Exception as exc:  # noqa: BLE001
            now = monotonic()
            await self._designer.cache.store(goal, spec, context=context, success=False)
            result = TopologyExecutionResult(
                goal=goal,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                spec_kind=spec.kind,
                cache_hit=cache_hit,
                n_agents=n_agents,
                depth=depth,
                design_ms=(t_designed - t0) * 1000.0,
                execution_ms=(now - t_designed) * 1000.0,
                total_ms=(now - t0) * 1000.0,
            )
            self._emit("topology.execution_failed", result, error=str(exc))
            raise

        now = monotonic()
        await self._designer.cache.store(goal, spec, context=context, success=True)
        result = TopologyExecutionResult(
            goal=goal,
            success=True,
            output=output,
            spec_kind=spec.kind,
            cache_hit=cache_hit,
            n_agents=n_agents,
            depth=depth,
            design_ms=(t_designed - t0) * 1000.0,
            execution_ms=(now - t_designed) * 1000.0,
            total_ms=(now - t0) * 1000.0,
        )
        self._emit("topology.execution_completed", result)
        return result

    def _emit(
        self,
        event_type: str,
        result: TopologyExecutionResult,
        **extra: Any,
    ) -> None:
        if self._bus is None:
            return
        try:
            import asyncio
            import contextlib

            data = {
                "goal": result.goal[:300],
                "success": result.success,
                "spec_kind": result.spec_kind,
                "cache_hit": result.cache_hit,
                "n_agents": result.n_agents,
                "depth": result.depth,
                "design_ms": result.design_ms,
                "execution_ms": result.execution_ms,
                "total_ms": result.total_ms,
                **extra,
            }
            event = AgentEvent(
                event_type=event_type,
                agent_name="topology_orchestrator",
                data=data,
            )
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                with contextlib.suppress(Exception):
                    asyncio.run(self._bus.emit(event))
                return
            loop.create_task(self._bus.emit(event))
        except Exception as exc:  # noqa: BLE001
            logger.debug("TopologyOrchestrator event emit failed: {e}", e=exc)


__all__ = [
    "TopologyExecutionResult",
    "TopologyOrchestrator",
]
