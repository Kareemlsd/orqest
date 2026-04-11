"""Tests for the JSONTracer and Span model."""

from datetime import datetime, timezone

from orqest.observability.tracer import JSONTracer, Span


class TestStartSpan:
    """Span creation via start_span."""

    def test_creates_span_with_uuid_ids(self) -> None:
        tracer = JSONTracer()
        span = tracer.start_span("do_work", agent_name="agent-a")

        assert isinstance(span.trace_id, str)
        assert len(span.trace_id) == 32  # uuid4 hex
        assert isinstance(span.span_id, str)
        assert len(span.span_id) == 32
        assert span.trace_id != span.span_id

    def test_parent_span_id_linked_for_nested_spans(self) -> None:
        tracer = JSONTracer()
        root = tracer.start_span("root", agent_name="a")
        child = tracer.start_span("child", agent_name="a", parent=root)

        assert child.parent_span_id == root.span_id
        assert child.trace_id == root.trace_id
        assert root.parent_span_id is None


class TestEndSpan:
    """Span completion via end_span."""

    def test_sets_ended_at_and_duration(self) -> None:
        tracer = JSONTracer()
        span = tracer.start_span("work", agent_name="a")
        tracer.end_span(span)

        assert span.ended_at is not None
        assert span.duration_ms is not None
        assert span.duration_ms >= 0.0
        assert span.status == "ok"

    def test_error_status(self) -> None:
        tracer = JSONTracer()
        span = tracer.start_span("fail", agent_name="a")
        tracer.end_span(span, status="error")

        assert span.status == "error"

    def test_attributes_merged(self) -> None:
        tracer = JSONTracer()
        span = tracer.start_span("work", agent_name="a")
        span.attributes["existing"] = 1
        tracer.end_span(span, attributes={"new_key": "value"})

        assert span.attributes == {"existing": 1, "new_key": "value"}


class TestGetSpans:
    """Span retrieval."""

    def test_returns_all_spans_in_order(self) -> None:
        tracer = JSONTracer()
        tracer.start_span("first", agent_name="a")
        tracer.start_span("second", agent_name="b")
        tracer.start_span("third", agent_name="c")

        spans = tracer.get_spans()
        assert [s.name for s in spans] == ["first", "second", "third"]
        # Returns a copy
        assert spans is not tracer._spans


class TestExportAndClear:
    """JSON export and clearing."""

    def test_export_json_produces_safe_dicts(self) -> None:
        tracer = JSONTracer()
        span = tracer.start_span("work", agent_name="agent-x")
        tracer.end_span(span, attributes={"key": 42})

        exported = tracer.export_json()
        assert len(exported) == 1
        d = exported[0]

        assert isinstance(d, dict)
        assert d["name"] == "work"
        assert d["agent_name"] == "agent-x"
        assert d["attributes"] == {"key": 42}
        assert isinstance(d["started_at"], str)
        assert isinstance(d["ended_at"], str)
        # Verify it parses back
        datetime.fromisoformat(d["started_at"])

    def test_clear_removes_all_spans(self) -> None:
        tracer = JSONTracer()
        tracer.start_span("a", agent_name="x")
        tracer.start_span("b", agent_name="y")
        assert len(tracer.get_spans()) == 2

        tracer.clear()
        assert tracer.get_spans() == []
