# Workbench — the Orqest agent-runtime container

Every production Orqest agent eventually needs the same four pieces of
infrastructure: a `MemoryStore` for durable facts, a `Tracer` for span
capture, an `EventBus` for observability fan-out, and a ring-buffer of
recent events so reconnecting clients can catch up on what they
missed. Wiring these four together was repeated across the Orqest demo
and every downstream consumer.

`Workbench` packages the quartet in one container. Construct it once
per session (or once per process for single-tenant apps), reach through
it to the underlying primitives, and pass it around instead of plumbing
four objects through every function signature.

## Minimal example

```python
import asyncio

from orqest import Workbench
from orqest.memory import LocalMemoryStore, MemoryEntry
from orqest.observability import AgentEvent


async def main() -> None:
    wb = Workbench(memory=LocalMemoryStore(db_path="/tmp/memory.db"))

    # Memory — persisted facts
    await wb.memory.store(MemoryEntry(content="User prefers tetrahedral elements"))

    # Tracing — span tree
    span = wb.tracer.start_span("generate_mesh")
    # ... do work ...
    wb.tracer.end_span(span, status="ok")

    # Events — fan-out
    await wb.event_bus.emit(AgentEvent(event_type="plan.init", agent_name="demo"))

    # One snapshot for the UI sidecar
    snap = wb.snapshot()
    assert "trace" in snap and "events" in snap


asyncio.run(main())
```

## Lifecycle patterns

- **Process-level** (demos, single-tenant CLIs) — build one workbench
  at startup, share it across requests.
- **Per-session** (chat apps) — build a workbench per session key;
  memory is a shared singleton injected in, tracer + bus are fresh.
- **Per-request** (multi-tenant backends) — fresh tracer + bus per
  turn, shared memory singleton.

Workbench doesn't force a pattern. Construct it however the consumer's
lifecycle demands; pass `memory=` always, optionally share or
instantiate the other three.

## Reset semantics

`wb.reset()` clears the tracer and the recent-events buffer. Memory
is **not** cleared — the point of memory is to outlive resets. If a
test needs a clean slate, reset memory explicitly through whatever
API the store exposes.

## Snapshot shape

`wb.snapshot()` returns:

```python
{
    "trace": [<span_dict>, ...],     # JSONTracer.export_json()
    "events": [<event_dict>, ...],    # bounded ring buffer
}
```

Memory is deliberately excluded — `MemoryStore` reads are async and
each backend decides its own query semantics. Consumers composing a
full sidecar response add memory alongside:

```python
async def sidecar_state(wb: Workbench) -> dict:
    snap = wb.snapshot()
    snap["memories"] = await wb.memory.recall("", k=30)
    return snap
```

## Reference

::: orqest.workbench.Workbench
