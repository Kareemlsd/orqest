# Hooks & Lifecycle

Orqest provides a fire-and-forget hook system for wrapping tool execution with before/after/error callbacks. The key guarantee: a broken hook never crashes your agent.

## ToolHook Protocol

`ToolHook` is a runtime-checkable protocol with three optional methods:

```python
from orqest.hooks import ToolHook

class LoggingHook:
    """Only implement the methods you need."""

    async def before_tool(self, tool_name: str, args: dict, state) -> None:
        print(f"[START] {tool_name} with {args}")

    async def after_tool(self, tool_name, args, result, state, duration_ms) -> None:
        print(f"[DONE] {tool_name} in {duration_ms:.0f}ms")

    # on_error is optional — skip it if you don't need error handling
```

| Method | When | Arguments |
|--------|------|-----------|
| `before_tool` | Before execution | `tool_name`, `args`, `state` |
| `after_tool` | After successful execution | `tool_name`, `args`, `result`, `state`, `duration_ms` |
| `on_error` | On exception | `tool_name`, `args`, `error`, `state` |

You only implement the methods you care about. `HookRunner` checks for method existence before calling, so partial implementations work.

## HookRunner

`HookRunner` dispatches events to registered hooks:

```python
import asyncio
from orqest.hooks import HookRunner


class MetricsHook:
    def __init__(self):
        self.call_count = 0
        self.total_ms = 0.0

    async def before_tool(self, tool_name, args, state):
        self.call_count += 1

    async def after_tool(self, tool_name, args, result, state, duration_ms):
        self.total_ms += duration_ms


async def main():
    metrics = MetricsHook()
    runner = HookRunner(hooks=[metrics])

    # Fire hooks manually (CompoundTool does this automatically)
    await runner.run_before("my_tool", {"query": "test"}, state=None)
    await runner.run_after("my_tool", {"query": "test"}, result="ok", state=None, duration_ms=42.0)
    await runner.run_error("my_tool", {"query": "test"}, error=ValueError("bad"), state=None)

    print(f"Calls: {metrics.call_count}, Total: {metrics.total_ms}ms")


asyncio.run(main())
```

### Error Resilience

Hook errors are logged at WARNING level and never re-raised:

```python
class BrokenHook:
    async def before_tool(self, tool_name, args, state):
        raise RuntimeError("This hook is broken")

runner = HookRunner(hooks=[BrokenHook(), MetricsHook()])

# BrokenHook fails silently, MetricsHook still runs
await runner.run_before("tool", {}, state=None)
```

This is the fire-and-forget pattern: hooks are side effects (logging, metrics, notifications) that must never interfere with the primary execution path.

## What's Happening Under the Hood

1. `HookRunner` iterates over registered hooks in order
2. For each hook, it calls `getattr(hook, method_name, None)` -- if the method doesn't exist, skip
3. If the method exists, call it inside a `try/except` that catches all exceptions
4. Exceptions are logged via `loguru.logger.warning` and swallowed

## Integration with CompoundTool

`CompoundTool` uses `HookRunner` internally. Hooks fire around the executor step (not the agent call):

```python
from orqest.agents import CompoundTool
from orqest.hooks import HookRunner

tool = CompoundTool(
    agent=my_agent,
    executor=my_executor,
    hooks=HookRunner(hooks=[LoggingHook(), MetricsHook()]),
)
```

See [Compound Tools](compound-tools.md) for the full pattern.

## Related Concepts

- [Compound Tools](compound-tools.md) -- the primary consumer of hooks
- [Observability](observability.md) -- tracing and events for broader observability
