"""Tracing primitives for agent execution observability.

Provides a Span data model and a Tracer protocol for recording agent execution.
JSONTracer is the default in-memory implementation with JSON export — zero
external dependencies required.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol


@dataclass
class Span:
    """A single unit of work within a trace.

    Spans form a tree via parent_span_id. A root span has parent_span_id=None
    and defines the trace_id that child spans inherit.
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    agent_name: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = None
    status: Literal["ok", "error"] = "ok"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


class Tracer(Protocol):
    """Protocol for trace collection backends."""

    def start_span(
        self,
        name: str,
        *,
        agent_name: str = "",
        parent: Span | None = None,
    ) -> Span:
        """Create and register a new span."""
        ...

    def end_span(
        self,
        span: Span,
        *,
        status: str = "ok",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Mark a span as finished."""
        ...

    def get_spans(self) -> list[Span]:
        """Return all recorded spans."""
        ...


class JSONTracer:
    """Default tracer — stores spans in memory, exports to JSON.

    Thread-safe for single-writer scenarios (typical async usage).
    No external dependencies.
    """

    def __init__(self) -> None:
        """Initialize with an empty span store."""
        self._spans: list[Span] = []

    def start_span(
        self, name: str, *, agent_name: str = "", parent: Span | None = None
    ) -> Span:
        """Create and register a new span.

        If a parent is provided, the child inherits its trace_id.
        Otherwise a new trace_id is generated (root span).
        """
        trace_id = parent.trace_id if parent else uuid.uuid4().hex
        span = Span(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex,
            parent_span_id=parent.span_id if parent else None,
            name=name,
            agent_name=agent_name,
            started_at=datetime.now(tz=UTC),
        )
        self._spans.append(span)
        return span

    def end_span(
        self,
        span: Span,
        *,
        status: str = "ok",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Mark a span as finished, computing its duration.

        Merges any extra attributes into the span.
        """
        span.ended_at = datetime.now(tz=UTC)
        span.duration_ms = (
            (span.ended_at - span.started_at).total_seconds() * 1000.0
        )
        span.status = status  # type: ignore[assignment]
        if attributes:
            span.attributes.update(attributes)

    def get_spans(self) -> list[Span]:
        """Return all recorded spans in insertion order."""
        return list(self._spans)

    def export_json(self) -> list[dict[str, Any]]:
        """Serialize all spans to JSON-safe dicts."""
        out: list[dict[str, Any]] = []
        for s in self._spans:
            out.append({
                "trace_id": s.trace_id,
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "name": s.name,
                "agent_name": s.agent_name,
                "started_at": s.started_at.isoformat(),
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "duration_ms": s.duration_ms,
                "status": s.status,
                "attributes": s.attributes,
                "events": s.events,
            })
        return out

    def clear(self) -> None:
        """Remove all recorded spans."""
        self._spans.clear()
