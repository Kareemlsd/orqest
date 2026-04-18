"""Observability primitives for orqest agents.

Provides tracing (Span, Tracer, JSONTracer) and event-driven observability
(AgentEvent, EventBus) with zero external dependencies.
"""

from .event_bus_hook import EventBusPublishHook
from .events import AgentEvent, EventBus
from .sse_sidecar import sse_sidecar
from .tracer import JSONTracer, Span, Tracer

__all__ = [
    "AgentEvent",
    "EventBus",
    "EventBusPublishHook",
    "JSONTracer",
    "Span",
    "Tracer",
    "sse_sidecar",
]
