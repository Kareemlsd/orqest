"""Watchdog protocol + Detection model.

A :class:`Watchdog` subscribes to an :class:`EventBus` and raises
:class:`Detection` records when its condition fires. Three concrete
implementations live in sibling modules: :class:`StallDetector`,
:class:`LoopDetector`, :class:`RegressionDetector`.

Detections are *observation-pure* — they describe what happened, not
what to do. The mapping from detection to recovery action is the
:class:`WatchdogHook`'s policy, kept separate so detectors stay
composable across consumers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from orqest.observability.events import EventBus


class Detection(BaseModel):
    """A signal raised by a :class:`Watchdog` when its condition fires."""

    detector: str
    severity: float = Field(ge=0.0, le=1.0, default=0.5)
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


@runtime_checkable
class Watchdog(Protocol):
    """A subsystem that observes the EventBus and raises Detections.

    Implementations subscribe via :meth:`subscribe` and either:

    * raise inline from event handlers, caching the latest Detection
      for the next :meth:`signal` poll (``LoopDetector``,
      ``RegressionDetector``); or
    * compute on demand at poll time (``StallDetector``).

    Subscriptions must be idempotent — calling :meth:`subscribe` twice
    must not cause duplicate handler dispatch.
    """

    name: str

    def subscribe(self, bus: EventBus) -> None: ...

    async def signal(self) -> Detection | None: ...
