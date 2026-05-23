"""Per-request topology design — the runtime planner sibling to MetaOrchestrator.

Where :class:`orqest.autonomy.MetaOrchestrator` decomposes a goal into a flat
``TaskDecomposition`` (a list of subtasks), :class:`RuntimeTopologyDesigner`
asks an LLM for a typed :data:`TopologySpec` (Pipeline / Parallel / Router /
RefinementLoop) per request, with an optional similarity-cache for reuse.
:class:`orqest.autonomy.topology_orchestrator.TopologyOrchestrator` wraps the
designer with the design-hydrate-run-record loop.

**Honest framing.** This module is *not* an optimizer in the classical sense
— there's no loss function, no per-request scoring, no Pareto archive. It's a
runtime planner with a cache. The shared :data:`TopologySpec` IR with
:class:`orqest.optimization.MetaAgentSearch` (which *is* an optimizer) is
infrastructure overlap, not a shared optimization model. To turn the cache's
exception-driven invalidation into real online optimization, see W3.E
(output-quality reliability signal) on the deferred roadmap.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol, runtime_checkable

from loguru import logger
from pydantic import TypeAdapter, ValidationError

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.autonomy.factory import AgentFactory
from orqest.memory.store import MemoryEntry, MemoryFilter, MemoryStore
from orqest.observability.events import AgentEvent, EventBus
from orqest.optimization.meta_agent import TopologyDesign
from orqest.orchestration.hydrate import (
    CallableRegistry,
    topology_from_spec,
)
from orqest.orchestration.spec import TopologySpec

_TOPOLOGY_ADAPTER: TypeAdapter[TopologySpec] = TypeAdapter(TopologySpec)


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------


@runtime_checkable
class TopologyCache(Protocol):
    """Pluggable cache for per-request topology synthesis.

    Implementations are async to allow embedder calls without blocking the
    request path. Three concrete shapes ship in this module:

    * :class:`NoCache` — zero state; every request re-synthesizes. The default.
    * :class:`InMemoryLRU` — exact-match goal string; demos and tests.
    * :class:`MemoryStoreCache` — production cache backed by
      :class:`orqest.memory.LocalMemoryStore` with reliability decay on failure.
    """

    async def lookup(
        self, goal: str, *, context: dict[str, Any] | None = None
    ) -> TopologySpec | None: ...

    async def store(
        self,
        goal: str,
        spec: TopologySpec,
        *,
        context: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None: ...


class NoCache:
    """Zero state — every request re-synthesizes.

    The default. Explicit, no surprise persistence; pick something else when
    you've measured the cache hit rate would actually pay off.
    """

    async def lookup(
        self, goal: str, *, context: dict[str, Any] | None = None
    ) -> TopologySpec | None:
        return None

    async def store(
        self,
        goal: str,
        spec: TopologySpec,
        *,
        context: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None:
        return None


class InMemoryLRU:
    """Exact-match cache on goal string with FIFO eviction at ``max_size``.

    Useful for demos / tests / single-process workloads where goals repeat
    verbatim. For fuzzy goal matching across processes / restarts, use
    :class:`MemoryStoreCache`.
    """

    def __init__(self, *, max_size: int = 128) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._max = max_size
        self._items: OrderedDict[str, TopologySpec] = OrderedDict()

    async def lookup(
        self, goal: str, *, context: dict[str, Any] | None = None
    ) -> TopologySpec | None:
        if goal in self._items:
            self._items.move_to_end(goal)
            return self._items[goal]
        return None

    async def store(
        self,
        goal: str,
        spec: TopologySpec,
        *,
        context: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None:
        if not success:
            # Failed runs evict the matching entry so the next request
            # re-designs rather than reusing a known-bad spec.
            self._items.pop(goal, None)
            return
        self._items[goal] = spec
        self._items.move_to_end(goal)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)


class MemoryStoreCache:
    """Production cache backed by :class:`orqest.memory.LocalMemoryStore`.

    Discovered topologies become "this shape worked for goals like that"
    entries with semantic-similarity recall and reliability decay on failure.
    All three behaviors come from the existing memory machinery — no new
    machinery is added by this class.

    **Embedder requirement (loud).** Without an embedder configured on the
    backing store, semantic recall falls back to FTS5 / LIKE, which is
    brittle for free-text goal similarity. The class still works (constructs
    fine; lookups just return ``None`` more often) so test wiring without an
    embedder doesn't crash, but production deployments should configure one.

    Storage shape:

    * ``memory_type="semantic"`` — not procedural. Procedural memory's
      :class:`Skill`-shape validator (memory/store.py) is too tight for
      arbitrary :data:`TopologySpec` payloads; we'd have to abuse the
      schema. Semantic with a namespaced ``source_agent`` keeps things
      clean and the embedder-based recall is exactly the right shape.
    * ``source_agent=namespace`` (default ``"topology_cache"``) — disambiguator
      from real semantic memories. Configurable so multiple isolated caches
      can coexist in the same store.
    * ``structured_content`` — the topology spec dumped to plain dict.
    * ``confidence=1.0`` on store; reliability decays via
      :meth:`MemoryStore.update_reliability` on failure.
    """

    def __init__(
        self,
        store: MemoryStore,
        *,
        threshold: float = 0.85,
        namespace: str = "topology_cache",
        min_reliability: float = 0.3,
        k: int = 1,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be in [0.0, 1.0]")
        if not 0.0 <= min_reliability <= 1.0:
            raise ValueError("min_reliability must be in [0.0, 1.0]")
        if k < 1:
            raise ValueError("k must be >= 1")
        self._store = store
        self._threshold = threshold
        self._namespace = namespace
        self._min_reliability = min_reliability
        self._k = k

    async def lookup(
        self, goal: str, *, context: dict[str, Any] | None = None
    ) -> TopologySpec | None:
        try:
            entries = await self._store.recall(
                query=goal,
                k=self._k,
                filters=MemoryFilter(
                    memory_type="semantic",
                    source_agent=self._namespace,
                    min_reliability=self._min_reliability,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("MemoryStoreCache.lookup failed: {e}", e=exc)
            return None

        for entry in entries:
            spec = self._entry_to_spec(entry)
            if spec is not None:
                return spec
        return None

    async def store(
        self,
        goal: str,
        spec: TopologySpec,
        *,
        context: dict[str, Any] | None = None,
        success: bool = True,
    ) -> None:
        if success:
            try:
                entry = MemoryEntry(
                    content=goal,
                    structured_content=spec.model_dump(mode="json"),
                    memory_type="semantic",
                    source_agent=self._namespace,
                    confidence=1.0,
                )
                await self._store.store(entry)
            except Exception as exc:  # noqa: BLE001
                logger.debug("MemoryStoreCache.store on success failed: {e}", e=exc)
            return

        # Failure path — decay reliability of the matching entry so the
        # existing decay machinery devalues it for future lookups.
        try:
            entries = await self._store.recall(
                query=goal,
                k=self._k,
                filters=MemoryFilter(
                    memory_type="semantic",
                    source_agent=self._namespace,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("MemoryStoreCache.store on failure recall failed: {e}", e=exc)
            return

        for entry in entries:
            try:
                await self._store.update_reliability(entry.id, success=False)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "MemoryStoreCache update_reliability failed for {eid}: {e}",
                    eid=entry.id,
                    e=exc,
                )

    @staticmethod
    def _entry_to_spec(entry: MemoryEntry) -> TopologySpec | None:
        payload = entry.structured_content
        if not isinstance(payload, dict):
            return None
        try:
            return _TOPOLOGY_ADAPTER.validate_python(payload)
        except ValidationError as exc:
            logger.debug(
                "MemoryStoreCache: stored entry {eid} fails TopologySpec validation: {e}",
                eid=entry.id,
                e=exc,
            )
            return None


# ---------------------------------------------------------------------------
# RuntimeTopologyDesigner
# ---------------------------------------------------------------------------


@dataclass
class _CacheStats:
    """Lightweight counters surfaced via :attr:`RuntimeTopologyDesigner.stats`."""

    lookups: int = 0
    hits: int = 0
    misses: int = 0
    stale_invalidations: int = 0
    designs: int = 0
    design_failures: int = 0
    fallback_returns: int = 0


class RuntimeTopologyDesigner:
    """Per-request topology synthesis. One LLM call → one :data:`TopologySpec`.

    Five-step flow per :meth:`design` call:

    1. Cache lookup. On hit and ``verify_on_hit=True``, the spec is hydrated
       against the *current* registries to catch stale agent / callable
       references. Stale hits fall through to step 2.
    2. Build the design prompt — constraints + registry allowlists +
       optional seed library + the goal itself. The :data:`TopologySpec`
       JSON schema is **not** embedded as text — pydantic-ai's structured
       output (:class:`TopologyDesign`) provides it natively, saving
       ~2-3k tokens vs. the search-time path.
    3. Invoke the user-provided ``designer_agent``.
    4. Validate the proposed spec hydrates against the current registries.
    5. Cache the success. On failure, return ``fallback_spec`` if configured,
       else raise :class:`RuntimeError`. **No debug-retry loop** — runtime is
       latency-sensitive.
    """

    def __init__(
        self,
        designer_agent: BaseAgent[Any, TopologyDesign],
        *,
        callable_registry: CallableRegistry,
        agent_registry: dict[str, Callable[[], BaseAgent[Any, Any]]],
        agent_factory: AgentFactory | None = None,
        constraints: str | None = None,
        max_depth: int = 4,
        cache: TopologyCache | None = None,
        seed_library: list[TopologySpec] | None = None,
        fallback_spec: TopologySpec | None = None,
        verify_on_hit: bool = True,
        bus: EventBus | None = None,
    ) -> None:
        """Wire the runtime designer.

        Args:
            designer_agent: User-provided :class:`BaseAgent` whose
                :class:`OutputT` is :class:`TopologyDesign`. The runtime path
                doesn't construct an internal pydantic-ai agent so consumers
                can plug in their preferred model / hooks / reasoning effort.
            callable_registry: Allowlist of named conditions / merges /
                state-updaters / function-steps. Surfaced verbatim to the
                designer in the prompt.
            agent_registry: Map from agent name to factory. Mirrors the
                shape :class:`TopologyEvaluator` accepts.
            agent_factory: Optional :class:`AgentFactory` for hydrating
                ``inline_spec`` references in proposed topologies. When
                ``None``, the designer is told inline spawning is disallowed.
            constraints: Optional natural-language guardrail surfaced to the
                designer (e.g. *"prefer simpler topologies; only branch when
                a Router clearly helps"*).
            max_depth: Cap surfaced to the designer — past this depth it's
                instructed to stop nesting.
            cache: Optional :class:`TopologyCache` implementation. Defaults
                to ``None`` (equivalent to :class:`NoCache`).
            seed_library: Optional list of validated topologies (typically
                the Pareto front from an offline :class:`MetaAgentSearch`
                run). Surfaced to the designer as "prefer composing one of
                these; only design from scratch when none fit."
            fallback_spec: Optional safe default returned when design fails
                or produces an unhydrable spec. ``None`` raises instead.
            verify_on_hit: When ``True`` (default), cached specs are
                hydration-tested before being returned — catches stale
                agent / callable references after registry changes.
            bus: Optional :class:`EventBus` for ``topology.*`` events.

        """
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        self._designer_agent = designer_agent
        self._callable_registry = callable_registry
        self._agent_registry = agent_registry
        self._agent_factory = agent_factory
        self._constraints = constraints
        self._max_depth = max_depth
        self._cache: TopologyCache = cache if cache is not None else NoCache()
        self._seed_library = list(seed_library) if seed_library else []
        self._fallback_spec = fallback_spec
        self._verify_on_hit = verify_on_hit
        self._bus = bus
        self._stats = _CacheStats()

    @property
    def cache(self) -> TopologyCache:
        return self._cache

    @property
    def stats(self) -> _CacheStats:
        return self._stats

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def design(
        self, goal: str, *, context: dict[str, Any] | None = None
    ) -> TopologySpec:
        """Synthesize a topology for *goal*. See class docstring for the flow."""
        # Step 1 — cache lookup
        self._stats.lookups += 1
        cached = await self._cache.lookup(goal, context=context)
        if cached is not None:
            if self._verify_on_hit and not self._is_hydratable(cached):
                self._stats.stale_invalidations += 1
                self._emit("topology.cache_hit", goal=goal, stale=True)
                # Fall through to a fresh design
            else:
                self._stats.hits += 1
                self._emit("topology.cache_hit", goal=goal, stale=False)
                return cached
        else:
            self._stats.misses += 1
            self._emit("topology.cache_miss", goal=goal)

        # Step 2 — build prompt + invoke designer
        return await self._design_fresh(goal, context=context)

    async def design_and_run(
        self, goal: str, *, context: dict[str, Any] | None = None
    ) -> Any:
        """Convenience: design + hydrate + run + record outcome."""
        from orqest.optimization.topology import (
            unpack_topology_output,  # local import to avoid cycle
        )

        spec = await self.design(goal, context=context)
        topology = topology_from_spec(
            spec,
            callable_registry=self._callable_registry,
            agent_registry=self._agent_registry,
            agent_factory=self._agent_factory,
        )
        try:
            run_result = await topology.run(goal)
            output = unpack_topology_output(run_result)
            await self._cache.store(goal, spec, context=context, success=True)
            return output
        except Exception:
            await self._cache.store(goal, spec, context=context, success=False)
            raise

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _design_fresh(
        self, goal: str, *, context: dict[str, Any] | None
    ) -> TopologySpec:
        prompt = self._build_design_prompt(goal, context)
        t0 = monotonic()
        try:
            state = GlobalState()
            state.add_message("user", prompt)
            run_result: Any = await self._designer_agent.run(state)
        except Exception as exc:  # noqa: BLE001
            self._stats.design_failures += 1
            self._emit("topology.design_failed", goal=goal, error=str(exc))
            return self._handle_design_failure(goal, context, exc)

        design = self._extract_design(run_result)
        if design is None:
            self._stats.design_failures += 1
            err = RuntimeError(
                "designer_agent returned an output that was not a TopologyDesign"
            )
            self._emit("topology.design_failed", goal=goal, error=str(err))
            return self._handle_design_failure(goal, context, err)

        spec = design.spec
        if not self._is_hydratable(spec):
            self._stats.design_failures += 1
            err = RuntimeError(
                f"designer_agent produced an unhydratable TopologySpec for goal {goal!r}"
            )
            self._emit("topology.design_failed", goal=goal, error=str(err))
            return self._handle_design_failure(goal, context, err)

        self._stats.designs += 1
        design_ms = (monotonic() - t0) * 1000.0
        self._emit(
            "topology.designed",
            goal=goal,
            spec_kind=spec.kind,
            design_ms=design_ms,
            thought=design.thought[:300],
        )
        await self._cache.store(goal, spec, context=context, success=True)
        return spec

    def _handle_design_failure(
        self,
        goal: str,
        context: dict[str, Any] | None,
        exc: Exception,
    ) -> TopologySpec:
        if self._fallback_spec is not None:
            self._stats.fallback_returns += 1
            self._emit("topology.fallback_used", goal=goal, error=str(exc))
            return self._fallback_spec
        raise RuntimeError(
            f"runtime topology design failed for goal {goal!r}: {exc}"
        ) from exc

    def _is_hydratable(self, spec: TopologySpec) -> bool:
        try:
            topology_from_spec(
                spec,
                callable_registry=self._callable_registry,
                agent_registry=self._agent_registry,
                agent_factory=self._agent_factory,
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("topology not hydratable: {e}", e=exc)
            return False
        return True

    @staticmethod
    def _extract_design(run_result: Any) -> TopologyDesign | None:
        """Pull the TopologyDesign out of whatever shape BaseAgent.run returned."""
        if isinstance(run_result, TopologyDesign):
            return run_result
        # AgentRunResult-shaped — has .output
        output = getattr(run_result, "output", run_result)
        if isinstance(output, TopologyDesign):
            return output
        # Last-ditch: a dict that validates as TopologyDesign
        if isinstance(output, dict):
            try:
                return TopologyDesign.model_validate(output)
            except ValidationError:
                return None
        return None

    def _build_design_prompt(
        self, goal: str, context: dict[str, Any] | None
    ) -> str:
        parts: list[str] = [f"## Goal\n{goal}"]
        if context:
            parts.append(f"## Context\n```json\n{json.dumps(context, default=str)}\n```")
        if self._constraints:
            parts.append(f"## Constraints (must satisfy)\n{self._constraints}")
        parts.append(
            "## Allowed agent_name values (from agent_registry)\n"
            f"{json.dumps(sorted(self._agent_registry.keys()))}"
        )
        parts.append(
            "## Allowed callable_name values (from callable_registry)\n"
            f"{json.dumps(self._callable_registry.names())}"
        )
        parts.append(
            "## Inline AgentSpec spawning\n"
            f"{'permitted' if self._agent_factory is not None else 'DISALLOWED — only use agent_name references'}"
        )
        parts.append(f"## Maximum nesting depth\n{self._max_depth}")
        if self._seed_library:
            lib = "\n\n".join(
                f"### Library entry {i + 1}\n```json\n{spec.model_dump_json(indent=2)}\n```"
                for i, spec in enumerate(self._seed_library)
            )
            parts.append(
                "## Library of validated topologies\n"
                "Prefer composing or specializing one of these; only design from "
                "scratch when none fit the goal.\n\n" + lib
            )
        parts.append(
            "## Output\n"
            "Emit a `thought` (1–3 sentences explaining your design choice) and a "
            "`spec` (TopologySpec JSON validating against the structured-output schema "
            "your runtime provides — never emit raw Python code)."
        )
        return "\n\n".join(parts)

    def _emit(self, event_type: str, **data: Any) -> None:
        if self._bus is None:
            return
        try:
            import asyncio
            import contextlib

            event = AgentEvent(
                event_type=event_type,
                agent_name="runtime_topology_designer",
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
            logger.debug("RuntimeTopologyDesigner event emit failed: {e}", e=exc)


__all__ = [
    "InMemoryLRU",
    "MemoryStoreCache",
    "NoCache",
    "RuntimeTopologyDesigner",
    "TopologyCache",
]
