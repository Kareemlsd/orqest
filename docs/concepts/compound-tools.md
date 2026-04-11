# Compound Tools

`CompoundTool` implements the **agent decides, system acts** pattern. An agent produces structured output, an executor runs a tool or action using that output, and state is optionally updated with the result. Hooks fire around the execution step.

## The Pattern

```
User prompt → Agent (structured output) → Executor (action) → State update
                                              ↑
                                     Hooks fire here
```

## Basic Usage

```python
import asyncio
from orqest.agents import BaseAgent, GlobalState, CompoundTool
from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, description="Number of results")


class SearchAgent(BaseAgent[GlobalState, SearchQuery]):
    async def _run_implementation(self, state: GlobalState, **kwargs) -> SearchQuery:
        user_message = state.get_latest_message("user")
        result = await self.call_model(user_message, state)
        return result.output


async def execute_search(query: SearchQuery, state: GlobalState):
    """The executor — runs the actual search."""
    return [f"Result {i} for: {query.query}" for i in range(query.max_results)]


async def main():
    agent = SearchAgent(
        agent_name="search_planner",
        system_prompt="Generate a search query from the user's request.",
        output_type=SearchQuery,
        model="openai:gpt-4.1",
        api_key="sk-...",
    )

    tool = CompoundTool(
        agent=agent,
        executor=execute_search,
    )

    state = GlobalState()
    state.add_message("user", "Find papers on quantum error correction")
    agent_output, results = await tool.run(state, prompt="Find papers on quantum error correction")
    print(f"Query: {agent_output.query}")
    print(f"Results: {results}")


asyncio.run(main())
```

## Hook Integration

Hooks fire around the executor step (not the agent call):

```python
from orqest.hooks import HookRunner


class AuditHook:
    async def before_tool(self, tool_name, args, state):
        print(f"[AUDIT] {tool_name} starting with {args['prompt']}")

    async def after_tool(self, tool_name, args, result, state, duration_ms):
        print(f"[AUDIT] {tool_name} completed in {duration_ms:.0f}ms")

    async def on_error(self, tool_name, args, error, state):
        print(f"[AUDIT] {tool_name} failed: {error}")


tool = CompoundTool(
    agent=agent,
    executor=execute_search,
    hooks=HookRunner(hooks=[AuditHook()]),
    name="search_tool",  # used in hook dispatch
)
```

## State Updater

An optional `state_updater` modifies state after execution:

```python
def update_state(state: GlobalState, result) -> GlobalState:
    state.add_message("assistant", f"Found {len(result)} results")
    return state

tool = CompoundTool(
    agent=agent,
    executor=execute_search,
    state_updater=update_state,
)
```

## What's Happening Under the Hood

1. `tool.run(state, prompt)` calls `agent.run(state)` to get structured output
2. `hooks.fire_before(tool_name, args, state)` dispatches to all hooks
3. `executor(agent_output, state)` runs the action, timed for `duration_ms`
4. On success: `hooks.fire_after(...)` fires, then `state_updater(state, result)` if configured
5. On error: `hooks.fire_error(...)` fires, then the exception re-raises

The return value is a tuple: `(agent_output, execution_result)`.

## Related Concepts

- [Hooks & Lifecycle](hooks-and-lifecycle.md) -- the hook system that CompoundTool uses
- [Agents](agents.md) -- the `BaseAgent` that produces structured output
- [Session Persistence](session-persistence.md) -- persisting state across compound tool invocations
