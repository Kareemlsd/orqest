# Orqest

A lightweight Python framework for building AI agents on top of [pydantic-ai](https://ai.pydantic.dev). Orqest provides a typed base agent class, multi-provider model routing, conversation state management, and agent composition primitives — so you can focus on your agent's logic instead of infrastructure.

> **Status:** Early development (v0.0.1). The API may change as the project matures.

## Features

- **Generic base agent** — `BaseAgent[StateT, OutputT]` gives you a typed, async-first foundation. Define your state and output models, implement `_run_implementation()`, done.
- **Multi-turn conversations** — `call_model()` automatically wires conversation history through pydantic-ai, with built-in sliding-window truncation that preserves turn integrity.
- **Multi-provider routing** — A single `provider:model_id` string routes to OpenAI, Anthropic, Google, or OpenRouter. No provider-specific code needed.
- **Agent-as-tool composition** — Wrap any agent as a pydantic-ai `Tool` with `as_tool()` for orchestrator patterns where specialized agents are called on demand.
- **Environment-based config** — `load_config()` reads `.env` files explicitly, with no import-time side effects.
- **System prompt loader** — Load `.txt` prompts from a `system_prompts/` directory with automatic upward search.

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

## What's Next

- [Getting Started](getting-started.md) — full walkthrough from installation to multi-turn conversations
- [Concepts](concepts/agents.md) — deep dives into agents, state management, and composition
- [API Reference](api/config.md) — auto-generated documentation from source
- [Changelog](changelog.md) — version history
