"""StallDetector — flags tool calls that exceed a timeout."""

from __future__ import annotations

from datetime import datetime, timezone

from orqest.healing.watchdog import Detection
from orqest.observability.events import AgentEvent, EventBus


class StallDetector:
    """Tracks open tool calls; raises :class:`Detection` when one exceeds
    ``timeout_s``.

    Subscribes to ``tool.before`` to mark a call as open and
    ``tool.after`` / ``tool.error`` to close it. :meth:`signal` is
    polled by :class:`HealingRunner` and returns at most one Detection
    per open call (subsequent polls for the same open call are
    suppressed).
    """

    name = "stall"

    def __init__(self, *, timeout_s: float = 60.0) -> None:
        self._timeout_s = timeout_s
        self._open_calls: dict[str, datetime] = {}
        self._fired: set[str] = set()
        self._subscribed: bool = False

    def subscribe(self, bus: EventBus) -> None:
        if self._subscribed:
            return
        bus.subscribe("tool.before", self._on_before)
        bus.subscribe("tool.after", self._on_after_or_error)
        bus.subscribe("tool.error", self._on_after_or_error)
        self._subscribed = True

    def _call_id(self, event: AgentEvent) -> str:
        tool_name = event.data.get("tool_name", "?") if event.data else "?"
        return f"{tool_name}::{event.timestamp.isoformat()}"

    async def _on_before(self, event: AgentEvent) -> None:
        cid = self._call_id(event)
        self._open_calls[cid] = (
            event.timestamp
            if event.timestamp.tzinfo is not None
            else event.timestamp.replace(tzinfo=timezone.utc)
        )

    async def _on_after_or_error(self, event: AgentEvent) -> None:
        # Close the *oldest* open call whose tool_name matches.
        tool_name = event.data.get("tool_name") if event.data else None
        if tool_name is None:
            return
        for cid in list(self._open_calls.keys()):
            if cid.startswith(f"{tool_name}::"):
                self._open_calls.pop(cid, None)
                self._fired.discard(cid)
                break

    async def signal(self) -> Detection | None:
        now = datetime.now(timezone.utc)
        for cid, started in list(self._open_calls.items()):
            if cid in self._fired:
                continue
            elapsed = (now - started).total_seconds()
            if elapsed > self._timeout_s:
                self._fired.add(cid)
                return Detection(
                    detector=self.name,
                    severity=min(1.0, elapsed / (self._timeout_s * 2)),
                    summary=f"Tool call open for >{self._timeout_s:.0f}s",
                    payload={
                        "call_id": cid,
                        "started_at": started.isoformat(),
                        "elapsed_s": elapsed,
                    },
                )
        return None
