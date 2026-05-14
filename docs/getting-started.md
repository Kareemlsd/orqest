# Getting Started

This guide walks you through installing orqest, configuring a provider, building your first agent, and having a multi-turn conversation.

## Installation

Requires **Python 3.12+**.

=== "pip"

    ```bash
    pip install orqest
    ```

=== "uv"

    ```bash
    uv add orqest
    ```

=== "From source"

    ```bash
    git clone https://github.com/Kareemlsd/orqest.git
    cd orqest
    pip install -e .
    ```

## Configuration

Create a `.env` file in your project root:

```bash
# Required
LLM_API_KEY=your_api_key_here
LLM_MODEL=openai:gpt-4.1

# Optional (defaults to LLM_API_KEY if not set)
EMBEDDING_API_KEY=your_embedding_key
EMBEDDING_MODEL=all-MiniLM-L6-v2
```

The `LLM_MODEL` value uses `provider:model_id` format:

| Provider | Prefix | Example |
|----------|--------|---------|
| OpenAI | `openai:` | `openai:gpt-4.1` |
| Anthropic | `anthropic:` | `anthropic:claude-sonnet-4-20250514` |
| Google | `google:` | `google:gemini-2.0-flash` |
| OpenRouter | `openrouter:` | `openrouter:anthropic/claude-3.5-sonnet` |

Load config in your code — orqest never reads environment variables at import time:

```python
from orqest import load_config

config = load_config()
print(config.llm_model)  # "openai:gpt-4.1"
```

## Define an Agent

Every orqest agent needs three things:

1. **An output type** — a Pydantic model defining the structured response
2. **A subclass of `BaseAgent`** — generic over a state type and the output type
3. **`_run_implementation()`** — the async method where your logic lives

```python
from pydantic import BaseModel, Field
from orqest.agents import BaseAgent, GlobalState


class AnalysisOutput(BaseModel):
    sentiment: str = Field(description="positive, negative, or neutral")
    confidence: float = Field(description="Confidence score 0-1")
    reasoning: str = Field(description="Why this sentiment was chosen")


class SentimentAgent(BaseAgent[GlobalState, AnalysisOutput]):
    def __init__(self, model: str, api_key: str):
        super().__init__(
            agent_name="sentiment_agent",
            system_prompt="Analyze the sentiment of the user's message.",
            output_type=AnalysisOutput,
            model=model,
            api_key=api_key,
        )

    async def _run_implementation(self, state: GlobalState, **kwargs) -> AnalysisOutput:
        user_message = state.get_latest_message("user")
        result = await self.call_model(user_message, state)
        return result.output
```

## Run the Agent

Create a `GlobalState`, add a user message, and call `await agent.run(state)`:

```python
config = load_config()
agent = SentimentAgent(model=config.llm_model, api_key=config.llm_api_key)

state = GlobalState()
state.add_message("user", "I absolutely love this new framework!")

output = await agent.run(state)
print(f"Sentiment: {output.sentiment} ({output.confidence:.0%})")
print(f"Reasoning: {output.reasoning}")
```

## Multi-Turn Conversation

Because `_run_implementation()` uses `self.call_model()`, conversation history is automatically managed. Each call stores the full message history on `state.message_history`, so the next call picks up where the previous one left off.

```python
# First turn
state = GlobalState()
state.add_message("user", "Analyze: I'm frustrated with the slow delivery.")
output1 = await agent.run(state)
print(f"Turn 1: {output1.sentiment}")

# Second turn — same state, agent has full context
state.add_message("user", "But the product itself is amazing!")
output2 = await agent.run(state)
print(f"Turn 2: {output2.sentiment}")

# History accumulates
print(f"Messages in history: {len(state.message_history)}")
```

The LLM sees the full conversation on the second call, so it can factor in both messages when analyzing sentiment.

!!! info "History truncation"
    By default, `keep_recent_messages()` limits history to the 100 most recent messages while preserving the first message and tool-call integrity. Configure this with the `truncated_history` constructor parameter or provide custom `history_processors`.

## Next Steps

- [Agents](concepts/agents.md) — constructor parameters, `call_model()` vs `self.agent.run()`, tools and toolsets
- [State & History](concepts/state-and-history.md) — how `GlobalState` works, custom state types, history processing
- [Agent as Tool](concepts/agent-as-tool.md) — composing agents with the `as_tool()` wrapper
- [Orchestration](concepts/orchestration.md) — pipeline, parallel, router, and refinement loop patterns
- [Hooks & Lifecycle](concepts/hooks-and-lifecycle.md) — fire-and-forget hook system for tool execution
- [Memory](concepts/memory.md) — pluggable memory with SQLite backend and full-text search
- [Observability](concepts/observability.md) — structured tracing and event bus
