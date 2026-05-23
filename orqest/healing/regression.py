"""RegressionDetector — flags confidence trends sliding downward.

Subscribes to ``metacognition.confidence`` events. If metacognition
isn't loaded (or no agents emit those events), no signal fires and the
detector silently no-ops — graceful degradation.
"""

from __future__ import annotations

import collections

from orqest.healing.watchdog import Detection
from orqest.observability.events import AgentEvent, EventBus


class RegressionDetector:
    """Confidence-trend watchdog.

    Maintains a sliding window of the last ``window_n`` confidence
    values. Fires when the head-half mean exceeds the tail-half mean by
    at least ``drop_threshold`` — i.e. the agent is becoming less
    certain over time.

    Cumulative-mean diff over half-windows is robust against single-
    sample noise without needing full statistics. Window size of 4-6
    typically suffices.
    """

    name = "regression"

    def __init__(self, *, window_n: int = 5, drop_threshold: float = 0.2) -> None:
        if window_n < 2:
            raise ValueError("window_n must be >= 2")
        if not 0.0 <= drop_threshold <= 1.0:
            raise ValueError("drop_threshold must be in [0, 1]")
        self._n = window_n
        self._drop = drop_threshold
        self._scores: collections.deque[float] = collections.deque(maxlen=window_n)
        self._latest: Detection | None = None
        self._fired_for_window: bool = False
        self._subscribed: bool = False

    def subscribe(self, bus: EventBus) -> None:
        if self._subscribed:
            return
        bus.subscribe("metacognition.confidence", self._on_confidence)
        self._subscribed = True

    async def _on_confidence(self, event: AgentEvent) -> None:
        if event.data is None:
            return
        score = event.data.get("confidence")
        if not isinstance(score, (int, float)):
            return
        f = float(score)
        if f < 0.0 or f > 1.0:
            return
        self._scores.append(f)
        if len(self._scores) < self._n:
            return

        scores = list(self._scores)
        half = len(scores) // 2
        head = sum(scores[:half]) / half
        tail = sum(scores[-half:]) / half
        drop = head - tail
        if drop >= self._drop and not self._fired_for_window:
            self._latest = Detection(
                detector=self.name,
                severity=min(1.0, drop / max(0.001, self._drop)),
                summary=f"Confidence dropped from {head:.2f} → {tail:.2f}",
                payload={"head_mean": head, "tail_mean": tail, "scores": scores},
            )
            self._fired_for_window = True
        elif drop < self._drop:
            # Reset suppression once the trend recovers.
            self._fired_for_window = False

    async def signal(self) -> Detection | None:
        d, self._latest = self._latest, None
        return d
