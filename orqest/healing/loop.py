"""LoopDetector — flags repeated identical tool calls."""

from __future__ import annotations

import collections
import hashlib
import json
from typing import Any

from orqest.healing.watchdog import Detection
from orqest.observability.events import AgentEvent, EventBus


def _hash_args(args: Any) -> str:
    """SHA256 of JSON-sorted args. Unhashable types coerce to str via
    ``default=str``. Returns first 16 hex chars — collision unlikely
    within a single window."""
    try:
        serialised = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        serialised = repr(args)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()[:16]


class LoopDetector:
    """Detects an agent looping on the same tool call.

    Maintains a deque of the last ``window_n`` ``(tool_name, args_hash)``
    pairs. When the current pair appears more than ``threshold_k`` times
    in the window, raises a Detection. Each fire suppresses subsequent
    detections until a different pair appears (so the watchdog doesn't
    spam the same loop).
    """

    name = "loop"

    def __init__(self, *, threshold_k: int = 3, window_n: int = 10) -> None:
        if threshold_k < 1:
            raise ValueError("threshold_k must be >= 1")
        if window_n < threshold_k:
            raise ValueError("window_n must be >= threshold_k")
        self._k = threshold_k
        self._n = window_n
        self._window: collections.deque[tuple[str, str]] = collections.deque(
            maxlen=window_n
        )
        self._latest: Detection | None = None
        self._last_fired_pair: tuple[str, str] | None = None
        self._subscribed: bool = False

    def subscribe(self, bus: EventBus) -> None:
        if self._subscribed:
            return
        bus.subscribe("tool.before", self._on_before)
        self._subscribed = True

    async def _on_before(self, event: AgentEvent) -> None:
        if event.data is None:
            return
        tool_name = event.data.get("tool_name", "")
        args = event.data.get("args", {})
        pair = (tool_name, _hash_args(args))
        self._window.append(pair)
        # Reset suppression once a different pair appears.
        if self._last_fired_pair is not None and pair != self._last_fired_pair:
            self._last_fired_pair = None
        count = sum(1 for x in self._window if x == pair)
        if count > self._k and pair != self._last_fired_pair:
            self._latest = Detection(
                detector=self.name,
                severity=min(1.0, count / (self._k * 2)),
                summary=(
                    f"Tool {tool_name!r} called {count} times with same args "
                    f"in last {len(self._window)} calls"
                ),
                payload={
                    "tool_name": tool_name,
                    "args_hash": pair[1],
                    "count": count,
                    "window_size": len(self._window),
                },
            )
            self._last_fired_pair = pair

    async def signal(self) -> Detection | None:
        d, self._latest = self._latest, None
        return d
