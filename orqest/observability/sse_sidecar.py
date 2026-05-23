"""Stream :class:`AgentEvent`\\s as Server-Sent Events.

``sse_sidecar`` subscribes to an :class:`EventBus`, converts every event
it receives into an SSE-formatted string chunk, and yields those chunks
as an async iterator suitable for ``StreamingResponse`` in FastAPI or
any ASGI framework.

Event format follows the SSE spec:

```
event: <AgentEvent.event_type>
id: <iso-timestamp>-<counter>
data: <json-serialized AgentEvent payload>

```

A heartbeat comment (``: keep-alive\\n\\n``) is emitted every
``heartbeat_s`` seconds to keep intermediaries from closing idle
connections. Optional replay of recent events lets a reconnecting
client catch up on what it missed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from orqest.observability.events import AgentEvent, EventBus


def _format_sse(event: AgentEvent, event_id: str) -> str:
    """Serialize an :class:`AgentEvent` to an SSE message block."""
    payload: dict[str, Any] = asdict(event)
    # datetime → iso string for JSON serialization
    ts = payload.get("timestamp")
    if isinstance(ts, datetime):
        payload["timestamp"] = ts.isoformat()
    data = json.dumps(payload, default=str, separators=(",", ":"))
    return f"event: {event.event_type}\nid: {event_id}\ndata: {data}\n\n"


def sse_sidecar(
    bus: EventBus,
    *,
    replay: Iterable[AgentEvent] = (),
    heartbeat_s: float = 15.0,
    queue_size: int = 256,
) -> AsyncIterator[str]:
    """Return an async iterator yielding SSE chunks for every event on *bus*.

    Subscription to the bus happens eagerly (before the returned
    iterator is consumed) so no events published after this call are
    lost, even if the caller awaits something else before starting to
    iterate.

    Args:
        bus: Source :class:`EventBus`. The sidecar subscribes globally
            via :meth:`EventBus.subscribe_all` immediately and
            unsubscribes when the consumer closes the iterator.
        replay: Historical events to emit before live streaming starts.
            Useful for letting a reconnecting client re-hydrate its view.
        heartbeat_s: Interval in seconds for keep-alive comments. Set
            large or ``float("inf")`` to disable.
        queue_size: Bound on the in-flight event queue. The bus producer
            never blocks: when the queue is full the *oldest* event is
            evicted to make room for the newest, and if eviction races
            another producer the new event is dropped silently. This
            protects the producer at the cost of event loss under
            sustained backpressure — a *bounded buffer with overflow
            drop*, not a guaranteed-delivery ring buffer. Size up if
            your consumer is slow enough that loss matters, or wire a
            slower-but-reliable transport instead.

    Returns:
        SSE-formatted async iterator. Pass directly to an ASGI
        ``StreamingResponse`` with ``media_type='text/event-stream'``.
    """
    queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=queue_size)

    def _push(event: AgentEvent) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest, enqueue newest — consumer is too slow to keep up
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # Subscribe eagerly so no events are missed between construction and first iteration.
    bus.subscribe_all(_push)

    async def _stream() -> AsyncIterator[str]:
        counter = 0
        try:
            # Replay first — lets reconnecting clients catch up
            for historic in replay:
                counter += 1
                yield _format_sse(historic, f"replay-{counter}")

            # Live loop with heartbeats
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_s)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                counter += 1
                event_id = f"{datetime.now(tz=UTC).isoformat()}-{counter}"
                yield _format_sse(event, event_id)
        finally:
            bus.unsubscribe_all(_push)

    return _stream()
