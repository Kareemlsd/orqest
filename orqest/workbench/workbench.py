"""Workbench — bundle memory + tracer + event bus + recent-events buffer + UI registry.

Every production Orqest agent needs the same infrastructure pieces: a
:class:`MemoryStore` for durable facts, a :class:`Tracer` for span
capture, an :class:`EventBus` for observability fan-out, a bounded
buffer of recent events so late-connecting clients (and reconnecting
SSE consumers) can catch up on what they missed, and a
:class:`ComponentRegistry` for generative-UI component schemas.
``Workbench`` packages those into a single container so consumers
configure them once and pass the workbench around instead of plumbing
the pieces through every function signature.

``Workbench`` does not prescribe a lifetime — callers decide. Typical
patterns:

* **Process-level** (demos, single-tenant CLI): one workbench, shared
  memory + tracer + bus for the process lifetime.
* **Per-request** (multi-tenant backend): a factory builds one
  workbench per user turn, sharing a singleton memory store but
  giving each request a fresh tracer + bus.
* **Per-session** (chat apps with sidecar streams): one workbench
  per chat session, outliving individual requests.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from orqest.observability.events import AgentEvent, EventBus
from orqest.observability.tracer import JSONTracer, Tracer


class Workbench:
    """Runtime container for memory, tracing, events, and replay.

    Instance attributes are public — reach through the workbench to
    talk to the underlying primitives directly when the canonical
    helpers aren't enough.

    Attributes:
        memory: A :class:`~orqest.memory.store.MemoryStore` (protocol;
            typically :class:`~orqest.memory.local.LocalMemoryStore`).
        tracer: A :class:`~orqest.observability.tracer.Tracer`
            (defaults to a fresh ``JSONTracer``).
        event_bus: A :class:`~orqest.observability.events.EventBus`
            (defaults to a fresh ``EventBus``).
        recent_events: Ring buffer of the last ``buffer_size`` events
            seen on the bus. Populated automatically by a subscription
            wired at construction.
    """

    def __init__(
        self,
        *,
        memory: Any,  # MemoryStore protocol; Any to avoid hard import cycle
        tracer: Tracer | None = None,
        event_bus: EventBus | None = None,
        buffer_size: int = 200,
        ui_registry: Any = None,
        auto_register_first_party_ui: bool = True,
    ) -> None:
        """Wire the infrastructure pieces together.

        Args:
            memory: A :class:`MemoryStore`. Must be constructed ahead
                of time — Workbench doesn't assume a default backend
                because memory choices (local SQLite, Supabase, mock)
                depend on the consumer.
            tracer: Optional tracer; a fresh ``JSONTracer`` is used
                when not supplied.
            event_bus: Optional event bus; a fresh one is created when
                not supplied.
            buffer_size: Max events retained in the ``recent_events``
                ring buffer. Zero disables buffering.
            ui_registry: Optional :class:`ComponentRegistry` (lazy
                imported). When ``None`` and
                ``auto_register_first_party_ui`` is True, a fresh
                registry pre-loaded with the first-party component set
                (see :func:`orqest.ui.default_registry`) is constructed.
                Pass an explicit registry to skip auto-registration or
                to add custom components.
            auto_register_first_party_ui: When True (default) and
                ``ui_registry`` is None, the first-party
                :func:`default_registry` is used. Set False for a
                bare-bones registry the consumer populates manually.
        """
        self.memory = memory
        self.tracer: Tracer = tracer if tracer is not None else JSONTracer()
        self.event_bus: EventBus = event_bus if event_bus is not None else EventBus()

        if ui_registry is None and auto_register_first_party_ui:
            from orqest.ui.registry import default_registry

            ui_registry = default_registry()
        elif ui_registry is None:
            from orqest.ui.registry import ComponentRegistry

            ui_registry = ComponentRegistry()
        self.ui_registry = ui_registry

        self.recent_events: deque[AgentEvent] = deque(
            maxlen=buffer_size if buffer_size > 0 else None
        )
        if buffer_size > 0:
            self.event_bus.subscribe_all(self._record_event)

    def _record_event(self, event: AgentEvent) -> None:
        """Append an event to the ring buffer (subscription callback)."""
        self.recent_events.append(event)

    def reset(self) -> None:
        """Clear tracer state and the recent-events buffer.

        Memory is NOT cleared — the whole point of memory is to
        outlive resets. Callers that want a full wipe (e.g. integration
        tests) should call ``memory.reset()`` or equivalent themselves.
        """
        clear = getattr(self.tracer, "clear", None)
        if callable(clear):
            clear()
        self.recent_events.clear()

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of trace + events.

        Memory is excluded because :class:`MemoryStore` access is
        async and consumer-specific. Callers compose the memory view
        themselves when serving a sidecar endpoint.
        """
        export = getattr(self.tracer, "export_json", None)
        trace_payload: list[dict[str, Any]] = (
            export() if callable(export) else []
        )
        return {
            "trace": trace_payload,
            "events": [_event_to_dict(e) for e in self.recent_events],
        }

    def with_healing(
        self,
        config: Any,
        *,
        api_key: Any | None = None,
    ) -> Any:
        """Construct a :class:`HealingRunner` wired to this workbench's bus.

        Convenience factory. Lazy-imports :mod:`orqest.healing` so this
        module stays import-light for consumers that don't use healing.

        **Construction alone does not start healing.** The runner only
        subscribes its watchdogs and starts the poll loop when entered
        as an async context manager. Forgetting the ``async with``
        leaves you with a silent no-op — no detections, no recoveries,
        no error. Always use the form below:

        .. code-block:: python

            async with workbench.with_healing(config) as runner:
                ...  # agent work happens inside this block

        Args:
            config: A :class:`HealingConfig` instance.
            api_key: Single key or per-provider map for the fallback
                model chain. Required only if ``config.fallback_models``
                is non-empty.

        Returns:
            An unstarted :class:`HealingRunner`. Enter it via ``async
            with`` to actually wire the watchdogs.
        """
        from orqest.healing import HealingRunner

        return HealingRunner(config, bus=self.event_bus, api_key=api_key)


def _event_to_dict(event: AgentEvent) -> dict[str, Any]:
    """Serialize an :class:`AgentEvent` to JSON-safe types."""
    timestamp = event.timestamp
    ts_iso = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
    return {
        "event_type": event.event_type,
        "agent_name": event.agent_name,
        "timestamp": ts_iso,
        "data": dict(event.data),
        "span_id": event.span_id,
        "trace_id": event.trace_id,
    }
