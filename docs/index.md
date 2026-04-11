# Orqest

A Python framework for building autonomous agentic AI systems on top of [pydantic-ai](https://ai.pydantic.dev). Orqest provides typed agent primitives, orchestration patterns, lifecycle hooks, memory, observability, and agent composition -- so you can focus on your agent's logic instead of infrastructure.

> **Status:** Active development (v0.0.1). Core agent primitives, orchestration, hooks, memory, and observability are implemented. API may evolve.

## Features

- **Generic base agent** -- `BaseAgent[StateT, OutputT]` gives you a typed, async-first foundation. Define your state and output models, implement `_run_implementation()`, done.
- **Orchestration** -- `Pipeline`, `Parallel`, `Router`, and `RefinementLoop` compose agents into complex workflows with error strategies, merge strategies, conditional routing, and iterative refinement.
- **Lifecycle hooks** -- `HookRunner` and `ToolHook` provide fire-and-forget before/after/error callbacks. Broken hooks never crash your agent.
- **Session persistence** -- `BaseSessionState` adds session tracking and JSON-safe serialization with ModelMessage round-tripping for cross-session persistence.
- **Compound tools** -- `CompoundTool` implements the agent-decides, system-acts pattern with hook integration and state updates.
- **Memory** -- `MemoryStore` protocol with `LocalMemoryStore` (SQLite + FTS5 full-text search), self-healing reliability decay, and pluggable backends.
- **Observability** -- Structured tracing with `Span` and `JSONTracer`, plus an `EventBus` pub/sub for agent events linked to traces.
- **Multi-turn conversations** -- `call_model()` automatically wires conversation history through pydantic-ai with sliding-window truncation.
- **Multi-provider routing** -- A single `provider:model_id` string routes to OpenAI, Anthropic, Google, or OpenRouter.
- **Agent-as-tool composition** -- Wrap any agent as a pydantic-ai `Tool` with `as_tool()` for orchestrator patterns.

## Quick Start

```python
import asyncio
from pydantic import BaseModel, Field
from orqest import load_config
from orqest.agents import BaseAgent, GlobalState


class SummaryOutput(BaseModel):
    summary: str = Field(description="A concise summary")
    key_points: list[str] = Field(description="Main ideas")


class SummaryAgent(BaseAgent[GlobalState, SummaryOutput]):
    async def _run_implementation(self, state: GlobalState, **kwargs) -> SummaryOutput:
        user_message = state.get_latest_message("user")
        result = await self.call_model(user_message, state)
        return result.output


async def main():
    config = load_config()
    agent = SummaryAgent(
        agent_name="summarizer",
        system_prompt="Summarize the user's message concisely.",
        output_type=SummaryOutput,
        model=config.llm_model,
        api_key=config.llm_api_key,
    )

    state = GlobalState()
    state.add_message("user", "Explain quantum computing in simple terms.")
    output = await agent.run(state)
    print(output.summary)


asyncio.run(main())
```

For multi-agent workflows, compose agents with orchestration primitives:

```python
from orqest.orchestration import Pipeline

pipeline = Pipeline([research_agent, draft_agent, review_agent], name="content")
result = await pipeline.run("Write about quantum computing")
```

## What's Next

- [Getting Started](getting-started.md) -- installation, configuration, and your first agent
- **Concepts:**
    - [Agents](concepts/agents.md) -- base agent, tools, streaming
    - [Orchestration](concepts/orchestration.md) -- pipeline, parallel, router, refinement loop
    - [Hooks & Lifecycle](concepts/hooks-and-lifecycle.md) -- fire-and-forget hook system
    - [Session Persistence](concepts/session-persistence.md) -- cross-session state serialization
    - [Compound Tools](concepts/compound-tools.md) -- agent-decides, system-acts pattern
    - [Memory](concepts/memory.md) -- pluggable memory with SQLite backend
    - [Observability](concepts/observability.md) -- tracing and event bus
- [API Reference](api/config.md) -- auto-generated documentation from source
- [Changelog](changelog.md) -- version history
