"""RecoveryAction discriminated union + WatchdogHook bridge.

A :class:`Watchdog` raises :class:`Detection` records (observation-pure).
A *policy* function maps each Detection to a :class:`RecoveryAction`
(intent). The :class:`WatchdogHook` runs the policy and translates the
intent into a :class:`HookDecision` that takes effect at the next
compound-flow boundary.

This three-layer split — detection / intent / decision — keeps
detectors composable across consumers. Numatics-AI may want a different
policy than a default open-source consumer; both reuse the same
detectors and the same :class:`HookDecision` plumbing.

The :data:`RecoveryAction` union is deliberately lean — :class:`AbortRun`
and :class:`EscalateToUser` are the two universal responses. Model-level
and tool-level recovery have dedicated, composable mechanisms instead:
:class:`~orqest.healing.fallback.FallbackModel` for provider failover,
:class:`~orqest.mcp.discovery_hook.DiscoveryHook` for missing-tool
recovery.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict

from orqest.healing.watchdog import Detection
from orqest.hooks import Abort, Continue, HookDecision, Skip
from orqest.observability.events import AgentEvent, EventBus


class _RecoveryBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EscalateToUser(_RecoveryBase):
    """Stop autonomous execution and ask the user a question."""

    kind: Literal["escalate"] = "escalate"
    question: str


class AbortRun(_RecoveryBase):
    """Abort the compound flow."""

    kind: Literal["abort"] = "abort"
    reason: str


RecoveryAction = EscalateToUser | AbortRun


# ---- default policy ---------------------------------------------------


def default_policy(detection: Detection) -> RecoveryAction:
    """Map a Detection to a sensible default RecoveryAction.

    Consumers can override by passing a custom policy to
    :class:`WatchdogHook`. The default is conservative: stalls/loops
    abort by default; regressions also abort.
    """
    if detection.detector == "stall":
        return AbortRun(reason=f"stall: {detection.summary}")
    if detection.detector == "loop":
        return AbortRun(reason=f"loop: {detection.summary}")
    if detection.detector == "regression":
        return AbortRun(reason=f"regression: {detection.summary}")
    return AbortRun(reason=f"unknown detector: {detection.detector}")


# ---- WatchdogHook -----------------------------------------------------


def _action_to_decision(action: RecoveryAction) -> HookDecision:
    """Convert intent into the :class:`HookDecision` that effects it."""
    if isinstance(action, AbortRun):
        return Abort(reason=action.reason)
    if isinstance(action, EscalateToUser):
        # No protocol path for user escalation in compound flows yet —
        # surface as Skip with the question payload so the caller can
        # see it in the after_tool stub_result. Documented limitation.
        return Skip(
            reason="escalation requested",
            stub_result={"escalation_question": action.question},
        )
    return Continue()


class WatchdogHook:
    """ToolHook that consults registered watchdogs and converts pending
    Detections into :class:`HookDecision` directives.

    Runs the policy on the *first* watchdog whose :meth:`signal`
    returns a Detection in registration order. Subsequent watchdogs are
    still polled so they advance their internal state, but their
    detections are dropped (no second decision fires per call).

    Returns ``None`` from :meth:`after_tool` and :meth:`on_error` —
    decisions only fire on :meth:`before_tool` (the natural seam where
    we can replace/skip the next call).
    """

    def __init__(
        self,
        watchdogs,
        *,
        policy: Callable[[Detection], RecoveryAction] | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._watchdogs = list(watchdogs)
        self._policy = policy or default_policy
        self._bus = bus

    async def before_tool(
        self, tool_name: str, args: dict[str, Any], state: Any
    ) -> HookDecision:
        active: HookDecision | None = None
        for wd in self._watchdogs:
            try:
                det = await wd.signal()
            except Exception as exc:
                logger.warning(
                    "Watchdog {n}.signal() failed: {e}",
                    n=getattr(wd, "name", type(wd).__name__),
                    e=exc,
                )
                continue
            if det is None:
                continue
            try:
                action = self._policy(det)
            except Exception as exc:
                logger.warning("Healing policy failed: {e}", e=exc)
                continue
            if self._bus is not None:
                await self._bus.emit(
                    AgentEvent(
                        event_type="healing.action",
                        agent_name="watchdog",
                        data={
                            "detection": det.model_dump(),
                            "action": action.model_dump(),
                        },
                    )
                )
            decision = _action_to_decision(action)
            if active is None:
                active = decision
        return active or Continue()
