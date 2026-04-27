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
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict

from orqest.healing.watchdog import Detection
from orqest.hooks import Abort, Continue, HookDecision, Redirect, Skip
from orqest.observability.events import AgentEvent, EventBus


class _RecoveryBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RetrySameTool(_RecoveryBase):
    """Re-issue the same tool call. Note describes why."""

    kind: Literal["retry_same"] = "retry_same"
    note: str = ""


class RetryDifferentModel(_RecoveryBase):
    """Re-issue the call but switch the model. ``model`` is a
    ``provider:model_id`` string accepted by ``resolve_model``."""

    kind: Literal["retry_diff_model"] = "retry_diff_model"
    model: str


class EscalateToUser(_RecoveryBase):
    """Stop autonomous execution and ask the user a question."""

    kind: Literal["escalate"] = "escalate"
    question: str


class AbortRun(_RecoveryBase):
    """Abort the compound flow."""

    kind: Literal["abort"] = "abort"
    reason: str


class DiscoverAndRetry(_RecoveryBase):
    """Discover a missing capability via MCP, then retry. ``capability``
    is the tool name to search for."""

    kind: Literal["discover"] = "discover"
    capability: str


RecoveryAction = (
    RetrySameTool
    | RetryDifferentModel
    | EscalateToUser
    | AbortRun
    | DiscoverAndRetry
)


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


def _action_to_decision(
    action: RecoveryAction, tool_name: str, args: dict[str, Any]
) -> HookDecision:
    """Convert intent into the :class:`HookDecision` that effects it."""
    if isinstance(action, AbortRun):
        return Abort(reason=action.reason)
    if isinstance(action, RetrySameTool):
        return Continue()
    if isinstance(action, RetryDifferentModel):
        return Redirect(
            new_args={**args, "_model": action.model},
            reason=f"healing: switch to {action.model}",
        )
    if isinstance(action, DiscoverAndRetry):
        return Redirect(
            new_args={**args, "_discover_capability": action.capability},
            reason="healing: discover-and-retry",
        )
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
    polled as well so they advance their internal state, but their
    detections are recorded as shadowed in a ``hook.shadowed`` event.

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
                # Surface a typed retry-initiated event for the chrome
                # so the healing toast layer can render "retrying X
                # because of stall/loop/regression" without parsing the
                # generic action payload.
                if isinstance(action, RetrySameTool):
                    await self._bus.emit(
                        AgentEvent(
                            event_type="healing.retry_initiated",
                            agent_name="watchdog",
                            data={
                                "tool_name": tool_name,
                                "detector": det.detector,
                                "summary": det.summary,
                                "severity": det.severity,
                            },
                        )
                    )
            decision = _action_to_decision(action, tool_name, args)
            if active is None:
                active = decision
        return active or Continue()
