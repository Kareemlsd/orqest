# EventBusPublishHook — bridge tool lifecycle to the EventBus

Orqest exposes two complementary observability primitives: a
[`HookRunner`](hooks-and-lifecycle.md) that fires before/after a tool
runs, and an [`EventBus`](observability.md) that fans events out to any
subscriber. Until now, wiring one to the other was boilerplate — every
consumer that wanted "publish a structured event for each tool call" had
to re-implement the same `await bus.emit(AgentEvent(...))` adapter.

`EventBusPublishHook` removes that friction. Register it on a
`HookRunner` and every compound tool call yields three events on the bus
(`tool.before`, `tool.after`, `tool.error`) with consistent payloads.
Subscribers — an SSE sidecar, a metrics exporter, a UI timeline — get a
uniform stream without coupling to `HookRunner` internals.

## Minimal example

```python
import asyncio

from orqest.hooks import HookRunner
from orqest.observability import AgentEvent, EventBus, EventBusPublishHook


async def main() -> None:
    bus = EventBus()

    def log(event: AgentEvent) -> None:
        print(f"[{event.event_type}] {event.data}")

    bus.subscribe_all(log)

    runner = HookRunner([EventBusPublishHook(bus, agent_name="demo")])

    await runner.run_before("do_work", {"task": "x"}, state=None)
    await runner.run_after("do_work", {"task": "x"}, result="ok", state=None, duration_ms=12.3)


asyncio.run(main())
```

Emits:

```
[tool.before] {'tool_name': 'do_work', 'args': {'task': 'x'}}
[tool.after]  {'tool_name': 'do_work', 'duration_ms': 12.3, 'result_preview': 'ok', 'result_len': 2}
```

## When to reach for this

- You want tool calls to show up in a dashboard, trace viewer, or the
  Vercel AI frontend without writing a custom hook.
- You have multiple subscribers (metrics, SSE, logging) — the bus lets
  them fan out without the hook knowing about any of them.
- You want tool events to carry consistent session/project metadata —
  `EventBusPublishHook` reads `state.session_id` / `state.project_id`
  via `getattr`, so any state object that exposes those fields works.

## Notes

- **Fire-and-forget contract**: both `HookRunner` and `EventBus` swallow
  handler errors. A broken subscriber can never break a tool call.
- **Payload bounding**: long tool results are truncated to
  `result_preview_chars` (default 400) with a `...` suffix. Full length
  is reported separately as `result_len` so consumers can show "result
  was 12 kB, preview shows first 400 chars".
- **Structural hook**: the class satisfies the
  [`ToolHook` protocol](hooks-and-lifecycle.md) structurally — no
  inheritance required.

## Reference

::: orqest.observability.EventBusPublishHook
