# Orqest

A lightweight Python framework for building AI agents on top of [pydantic-ai](https://ai.pydantic.dev). Provides a typed base agent class, multi-provider model routing, conversation state management, and agent composition primitives.

> **Status:** Early development (v0.0.1). The API may change as the project matures.

## Quick Start

Requires **Python 3.12+**.

```bash
pip install orqest
```

Create a `.env` file:

```bash
LLM_API_KEY=your_api_key_here
LLM_MODEL=openai:gpt-4o
```

Build and run an agent:

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

## Features

- **Generic base agent** — `BaseAgent[StateT, OutputT]` with async-first execution and structured output via Pydantic models
- **Multi-turn conversations** — `call_model()` automatically wires conversation history, with sliding-window truncation that preserves turn integrity
- **Multi-provider routing** — `provider:model_id` format routes to OpenAI, Anthropic, Google, or OpenRouter
- **Agent-as-tool composition** — `as_tool()` wraps any agent as a pydantic-ai `Tool` for orchestrator patterns
- **Environment-based config** — `load_config()` reads `.env` files explicitly, no import-time side effects
- **System prompt loader** — `load_sys_prompt()` finds and loads `.txt` prompts from a `system_prompts/` directory

## Supported Providers

| Provider | Format | Example |
|----------|--------|---------|
| OpenAI | `openai:model_id` | `openai:gpt-4o` |
| Anthropic | `anthropic:model_id` | `anthropic:claude-sonnet-4-20250514` |
| Google | `google:model_id` | `google:gemini-2.0-flash` |
| OpenRouter | `openrouter:model_id` | `openrouter:anthropic/claude-3.5-sonnet` |

## Documentation

Full documentation is available at the [docs site](https://kareemlsd.github.io/orqest/), including:

- [Getting Started](https://kareemlsd.github.io/orqest/getting-started/) — installation through multi-turn conversations
- [Concepts](https://kareemlsd.github.io/orqest/concepts/agents/) — agents, state management, agent-as-tool composition
- [API Reference](https://kareemlsd.github.io/orqest/api/config/) — auto-generated from source
- [Changelog](https://kareemlsd.github.io/orqest/changelog/)

## Contributing

Contributions are welcome. This project is in its early stages — if you'd like to help shape its direction, open an issue or submit a pull request.

## License

[MIT](LICENSE)
