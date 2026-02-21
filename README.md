# Orqest

A lightweight Python framework for building AI agents on top of [pydantic-ai](https://github.com/pydantic/pydantic-ai). Orqest provides a structured base class, multi-provider model routing, and conversation state management so you can focus on your agent's logic instead of boilerplate.

> **Status:** Early development (v0.0.1). The API may change as the project matures.

## Features

- **Generic base agent** — `BaseAgent[StateT, OutputT]` gives you a typed, async-first foundation for any agent. Define your input state and output model, implement `_run_implementation()`, and you're done.
- **Multi-provider model routing** — A single `model()` factory auto-selects the right pydantic-ai provider (OpenAI, Anthropic, Google, OpenRouter) based on an environment variable.
- **Conversation state** — `GlobalState` is a ready-made Pydantic model for tracking messages, with helpers for retrieving the latest user or assistant message.
- **History processing** — Built-in sliding-window history truncation that preserves tool-call integrity, with support for custom history processors.
- **Tool & toolset support** — Register individual tools or entire toolsets on any agent.
- **System prompt loader** — A utility to load system prompts from `.txt` files by searching upward for a `system_prompts/` directory.
- **Environment-based config** — Reads `LLM_API_KEY`, `LLM_MODEL`, `EMBEDDING_MODEL`, and `EMBEDDING_API_KEY` from `.env` or environment variables.

## Installation

Requires **Python 3.12+**.

```bash
pip install orqest
```

Or install from source for development:

```bash
git clone https://github.com/Kareemlsd/orqest.git
cd orqest
pip install -e .
```

## Configuration

Create a `.env` file in your project root (or set the variables directly in your environment):

```bash
# Required
LLM_API_KEY=your_api_key_here
LLM_MODEL=gpt-3.5-turbo          # see "Supported Providers" below

# Optional (defaults to LLM_API_KEY if not set)
EMBEDDING_API_KEY=your_embedding_key
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

### Supported Providers

The model is selected automatically based on the `LLM_MODEL` value:

| `LLM_MODEL` value | Provider | Example |
|---|---|---|
| Contains `claude` | Anthropic | `claude-sonnet-4-20250514` |
| Contains `gemini` | Google | `gemini-2.0-flash` |
| Prefixed with `openrouter:` | OpenRouter | `openrouter:anthropic/claude-3.5-sonnet` |
| Anything else | OpenAI | `gpt-4o`, `gpt-3.5-turbo` |

## Quick Start

```python
import asyncio
from pydantic import BaseModel, Field
from orqest.agents import BaseAgent, GlobalState


class SummaryOutput(BaseModel):
    """Structured output for the summary agent."""
    summary: str = Field(description="A concise summary")


class SummaryAgent(BaseAgent[GlobalState, SummaryOutput]):
    def __init__(self):
        super().__init__(
            agent_name="summary_agent",
            system_prompt="You are a helpful assistant. Summarize the user's message concisely.",
            output_type=SummaryOutput,
        )

    async def _run_implementation(self, state: GlobalState, **kwargs) -> SummaryOutput:
        user_message = state.get_latest_user_message()
        result = await self.agent.run(user_message)
        return result.output


async def main():
    agent = SummaryAgent()

    state = GlobalState()
    state.add_message("user", "Explain quantum computing in detail.")

    output = await agent.run(state)
    if output:
        print(output.summary)


if __name__ == "__main__":
    asyncio.run(main())
```

## Package Structure

```
orqest/
├── __init__.py              # Re-exports config values
├── config.py                # Loads .env, exports LLM_API_KEY, LLM_MODEL, etc.
├── agents/
│   ├── __init__.py          # Re-exports BaseAgent, GlobalState
│   ├── base_agent.py        # BaseAgent[StateT, OutputT] — the core abstract class
│   └── state.py             # GlobalState — shared conversation state model
├── utils/
│   └── llm_model.py         # model() factory — multi-provider routing
└── io_utils/
    └── load_sys_prompt.py   # load_sys_prompt() — loads prompts from system_prompts/
```

## Core API

### `BaseAgent[StateT, OutputT]`

The abstract base class for all agents. Generic over an input state type and an output type (both Pydantic models).

**Constructor parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `agent_name` | `str` | — | Name used for logging and identification |
| `system_prompt` | `str` | — | System prompt guiding agent behavior |
| `output_type` | `Type[OutputT]` | — | Pydantic model for structured output |
| `retries` | `int` | `3` | Retry attempts for failed LLM calls |
| `deps_type` | `Any` | `None` | Dependency type injected into the agent |
| `tools` | `List[Tool]` | `None` | Individual tools to register |
| `toolsets` | `List[Any]` | `None` | Toolset objects providing collections of tools |
| `agent` | `Agent` | `None` | Pre-configured pydantic-ai Agent (skips auto-creation) |
| `model` | `Callable` | `None` | Custom model factory (defaults to `orqest.utils.llm_model.model`) |
| `truncated_history` | `int` | `100` | Max recent messages to keep in history |
| `history_processors` | `HistoryProcessor \| List` | `None` | Custom history processor(s); defaults to `keep_recent_messages` |

**Key methods:**

- `async run(state, **kwargs) -> OutputT | None` — Public entry point. Calls `_run_implementation()` with error handling.
- `async _run_implementation(state, **kwargs) -> OutputT` — **Abstract.** Implement your agent logic here.
- `keep_recent_messages(messages) -> messages` — Default history processor. Truncates to the most recent N messages while preserving tool-call groupings.

### `GlobalState`

A Pydantic model for shared conversation state.

**Fields:** `messages`, `assistant_message`, `message_history`

**Methods:**
- `add_message(role, content)` — Append a message
- `get_latest_user_message() -> str | None` — Get the most recent user message
- `get_latest_assistant_message() -> str | None` — Get the most recent assistant message

### `load_sys_prompt(filename, start=None) -> str`

Searches upward from the caller's location (or `start`) for a `system_prompts/` directory and returns the contents of the specified file.

```python
from orqest.io_utils import load_sys_prompt

prompt = load_sys_prompt("my_agent.txt")
```

## Contributing

Contributions are welcome. This project is in its early stages — if you'd like to help shape its direction, open an issue or submit a pull request.

## License

[MIT](LICENSE)
