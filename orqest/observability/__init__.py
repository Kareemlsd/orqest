"""Observability primitives for orqest agents.

Provides tracing (Span, Tracer, JSONTracer) and event-driven observability
(AgentEvent, EventBus) with zero external dependencies.
"""

from .events import AgentEvent, EventBus
from .tracer import JSONTracer, Span, Tracer

__all__ = [
    "AgentEvent",
    "EventBus",
    "JSONTracer",
    "Span",
    "Tracer",
]
