"""Per-session :class:`~orqest.Workbench` construction.

One Workbench per session bundles memory + tracer + event bus +
recent-events buffer (see ``docs/concepts/workbench.md``). This factory
also builds a :class:`~orqest.HookRunner` pre-wired with three hooks:

* :class:`~orqest.observability.EventBusPublishHook` — publishes
  ``tool.before/after/error`` so any subscriber sees compound-flow
  activity.
* :class:`~orqest.metacognition.MetacognitionHook` (Phase α) — surfaces
  ``metacognition.confidence`` events when a tool result is an
  :class:`~orqest.EnrichedOutput`.
* :class:`TakeoverGate` (Phase β.7) — returns
  :class:`~orqest.hooks.Skip` from ``before_tool`` while the user has
  takeover, deferring tool execution without rejecting the chat turn.

When ``ENABLE_HEALING`` is on, :func:`build_workbench` also constructs a
:class:`~orqest.healing.HealingRunner` and registers
``runner.hook`` (the watchdog hook) on the same ``HookRunner``. The
runner's poll loop is started lazily by the chat router via
:meth:`SessionRuntime.ensure_started` so we don't make
:func:`get_runtime` async.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orqest import HookRunner, Workbench
from orqest.healing import HealingConfig, HealingRunner
from orqest.hooks import Continue, HookDecision, Skip
from orqest.memory import LocalMemoryStore
from orqest.metacognition import MetacognitionHook
from orqest.observability import EventBus, EventBusPublishHook, JSONTracer

from polymath.config import get_default_config
from polymath.embedder import maybe_make_embedder
from polymath.tab_respawn import attach_respawn


class TakeoverGate:
    """ToolHook that defers tool execution while user takeover is active.

    On ``before_tool`` returns :class:`~orqest.hooks.Skip` with a
    ``stub_result`` describing the deferral. ``after_tool`` still fires
    so observers see the skip recorded as a no-op tool call. The chat
    stream therefore completes a turn even while takeover is active —
    tool calls return their stub results and the agent summarizes.

    Reads ``runtime.takeover_active`` lazily via :func:`get_runtime`
    (imported at call time to avoid an import cycle with
    :mod:`polymath.runtime`). The session id is captured at construction.
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    async def before_tool(
        self, tool_name: str, args: dict[str, Any], state: Any
    ) -> HookDecision:
        # Deferred import: workbench_factory is imported by runtime.py.
        from polymath.runtime import _runtimes

        rt = _runtimes.get(self._session_id)
        if rt is None or not rt.takeover_active:
            return Continue()
        return Skip(
            reason="user has control",
            stub_result={
                "deferred": True,
                "tool_name": tool_name,
                "message": "Tool deferred - user is driving the sandbox.",
            },
        )


@dataclass(slots=True)
class SessionRuntime:
    """Bundle of per-session runtime infra returned by :func:`build_workbench`."""

    workbench: Workbench
    hook_runner: HookRunner
    healing_runner: HealingRunner | None = None
    takeover_active: bool = False
    _started: bool = field(default=False, repr=False)

    async def ensure_started(self) -> None:
        """Start the healing runner's poll loop if not yet running.

        Idempotent. Called from request handlers (e.g. the chat stream)
        before the first turn so :func:`get_runtime` can stay sync.
        """
        if self._started:
            return
        if self.healing_runner is not None:
            await self.healing_runner.start()
        self._started = True

    async def shutdown(self) -> None:
        """Stop the healing runner's poll loop. Idempotent."""
        if self.healing_runner is not None and self._started:
            await self.healing_runner.stop()
        self._started = False


def build_workbench(session_id: str) -> SessionRuntime:
    """Construct a fresh :class:`Workbench` + :class:`HookRunner` for *session_id*.

    Memory is a SQLite DB under ``cfg.MEMORY_DIR/{sid}.db`` so sessions are
    isolated on disk; the directory is created lazily on first write.

    Hook registration order matters because :class:`HookRunner` aggregates
    decisions first-non-Continue-wins:

    1. :class:`EventBusPublishHook` — observation only, never decides.
    2. :class:`MetacognitionHook` — observation only, never decides.
    3. :class:`TakeoverGate` — gates *every* tool call when takeover is
       active. Sits before the watchdog so a Skip wins over a watchdog
       Abort while the user is driving.
    4. :class:`~orqest.healing.WatchdogHook` (when healing enabled) —
       last so it only fires when the gate above is clear.
    """
    cfg = get_default_config()
    cfg.MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    # Optional: wire an OpenAI embedder so semantic recall actually works on
    # free-text concept queries ("find me anything about spectral
    # decomposition") rather than FTS5 LIKE matching. Returns None gracefully
    # when OPENAI_API_KEY isn't set — LocalMemoryStore handles that natively.
    embedder = maybe_make_embedder()
    memory = LocalMemoryStore(
        db_path=cfg.MEMORY_DIR / f"{session_id}.db",
        embedder=embedder,
    )
    tracer = JSONTracer()
    bus = EventBus()

    workbench = Workbench(memory=memory, tracer=tracer, event_bus=bus)

    # Auto-respawn the right-pane system tabs (Shell / Files / Editor /
    # Browser / Report / Charts) on the first relevant tool / artifact
    # event per session. Idempotent — closed tabs pop back when the
    # corresponding tools fire again. See :mod:`polymath.tab_respawn`.
    attach_respawn(bus, session_id)

    healing_runner: HealingRunner | None = None
    if cfg.ENABLE_HEALING:
        healing_runner = workbench.with_healing(
            HealingConfig(
                fallback_models=cfg.FALLBACK_MODELS,
                # Cross-feature handshake with metacognition: the
                # MetacognitionHook above publishes
                # ``metacognition.confidence`` events that
                # :class:`RegressionDetector` subscribes to.
                enable_regression=True,
            ),
            api_key=cfg.LLM_API_KEY,
        )

    hooks: list[Any] = [
        EventBusPublishHook(bus, agent_name=f"polymath[{session_id}]"),
        # Phase α: surface ``metacognition.confidence`` events when a
        # tool returns an :class:`EnrichedOutput`. The frontend
        # subscribes via ``useSidecar``'s event whitelist.
        MetacognitionHook(bus, agent_name=f"polymath[{session_id}]"),
        # Phase β.7: takeover gate as Skip. Replaces the router-side 409
        # block so chat turns complete with deferred tool stubs.
        TakeoverGate(session_id=session_id),
    ]
    if healing_runner is not None:
        hooks.append(healing_runner.hook)

    hook_runner = HookRunner(hooks=hooks)
    return SessionRuntime(
        workbench=workbench,
        hook_runner=hook_runner,
        healing_runner=healing_runner,
    )
