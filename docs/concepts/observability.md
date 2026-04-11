# Observability

Orqest provides two observability primitives: **Tracer** for structured span-based tracing and **EventBus** for pub/sub agent events. Both are zero-dependency, in-process implementations that follow the fire-and-forget pattern.

## Tracing

### Span

A `Span` represents a unit of work within a trace. Spans form a tree via `parent_span_id`:

| Field | Type | Description |
|-------|------|-------------|
| `trace_id` | `str` | Groups related spans into a single trace |
| `span_id` | `str` | Unique identifier for this span |
| `parent_span_id` | `str \| None` | `None` for root spans |
| `name` | `str` | Human-readable operation name |
| `agent_name` | `str` | Which agent owns this span |
| `started_at` | `datetime` | UTC start time |
| `ended_at` | `datetime \| None` | UTC end time (set by `end_span`) |
| `duration_ms` | `float \| None` | Computed on `end_span` |
| `status` | `"ok"` or `"error"` | Outcome |
| `attributes` | `dict` | Arbitrary key-value metadata |
| `events` | `list[dict]` | Timestamped events within the span |

### JSONTracer

The default tracer stores spans in memory and exports to JSON:

```python
import asyncio
from orqest.observability import JSONTracer


async def main():
    tracer = JSONTracer()

    # Start a root span
    root = tracer.start_span("pipeline_run", agent_name="orchestrator")

    # Start a child span
    child = tracer.start_span("step_1", agent_name="researcher", parent=root)
    # ... do work ...
    tracer.end_span(child, status="ok", attributes={"tokens": 150})

    # End root span
    tracer.end_span(root, status="ok")

    # Export all spans as JSON
    spans_json = tracer.export_json()
    for s in spans_json:
        print(f"{s['name']}: {s['duration_ms']:.1f}ms [{s['status']}]")

    # Clear recorded spans
    tracer.clear()


asyncio.run(main())
```

### Tracer Protocol

Custom tracer backends implement the `Tracer` protocol:

```python
from orqest.observability import Tracer, Span

class MyTracer:
    def start_span(self, name: str, *, agent_name: str = "", parent: Span | None = None) -> Span:
        ...

    def end_span(self, span: Span, *, status: str = "ok", attributes: dict | None = None) -> None:
        ...

    def get_spans(self) -> list[Span]:
        ...
```

## EventBus

An in-process pub/sub dispatcher for `AgentEvent` objects. Supports both sync and async handlers.

```python
import asyncio
from orqest.observability import EventBus, AgentEvent


async def on_tool_call(event: AgentEvent):
    print(f"[{event.agent_name}] {event.event_type}: {event.data}")

def on_any_event(event: AgentEvent):
    """Sync handlers work too."""
    print(f"EVENT: {event.event_type}")


async def main():
    bus = EventBus()

    # Subscribe to specific event types
    bus.subscribe("tool_call", on_tool_call)

    # Subscribe to all events
    bus.subscribe_all(on_any_event)

    # Emit an event
    await bus.emit(AgentEvent(
        event_type="tool_call",
        agent_name="search_agent",
        data={"tool": "web_search", "query": "quantum computing"},
    ))

    # Unsubscribe
    bus.unsubscribe("tool_call", on_tool_call)


asyncio.run(main())
```

### AgentEvent

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `event_type` | `str` | required | Event classification (e.g., `"tool_call"`, `"step_complete"`) |
| `agent_name` | `str` | required | Originating agent |
| `timestamp` | `datetime` | UTC now | When the event occurred |
| `data` | `dict` | `{}` | Arbitrary payload |
| `span_id` | `str \| None` | `None` | Link to a trace span |
| `trace_id` | `str \| None` | `None` | Link to a trace |

### Linking Events to Traces

Connect events to spans for correlated observability:

```python
tracer = JSONTracer()
bus = EventBus()

span = tracer.start_span("agent_run", agent_name="my_agent")

await bus.emit(AgentEvent(
    event_type="model_call",
    agent_name="my_agent",
    data={"model": "gpt-4.1", "tokens": 500},
    span_id=span.span_id,
    trace_id=span.trace_id,
))

tracer.end_span(span)
```

### Fire-and-Forget Handlers

Handler errors are logged at WARNING level and never propagated, matching the pattern from [Hooks & Lifecycle](hooks-and-lifecycle.md):

```python
async def broken_handler(event):
    raise RuntimeError("This handler is broken")

bus.subscribe("tool_call", broken_handler)
# Emitting still works — broken_handler fails silently, other handlers run
await bus.emit(event)
```

## What's Happening Under the Hood

**Tracer:**

1. `start_span()` generates UUIDs for `span_id` and (for root spans) `trace_id`
2. Child spans inherit `trace_id` from their parent
3. `end_span()` computes `duration_ms` from the timestamp delta and merges attributes

**EventBus:**

1. `emit()` collects type-specific handlers, then global handlers
2. Each handler is called independently inside `_safe_call()`
3. If the handler returns a coroutine, it is awaited
4. Exceptions are caught, logged, and swallowed

## Related Concepts

- [Hooks & Lifecycle](hooks-and-lifecycle.md) -- fire-and-forget pattern for tool-level callbacks
- [Orchestration](orchestration.md) -- pipeline events that can feed into the EventBus
