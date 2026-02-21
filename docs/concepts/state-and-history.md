# State & History

## GlobalState

`GlobalState` is the built-in state model for orqest agents. It tracks two distinct things:

- **`messages`** — an application-level conversation log (`list[dict]` with `role` and `content` keys). This is for your code to read and write.
- **`message_history`** — raw pydantic-ai `ModelMessage` objects (`list[ModelMessage]`). This is what gets passed to the LLM for context.

These two stores serve different purposes and don't need to stay in sync. `messages` is a human-readable log; `message_history` is the raw LLM conversation managed by `call_model()`.

### Adding and Reading Messages

```python
from orqest.agents import GlobalState

state = GlobalState()

# Add messages to the app-level log
state.add_message("user", "What is quantum computing?")
state.add_message("assistant", "Quantum computing uses qubits...")

# Read the most recent message for a given role
latest_user = state.get_latest_message("user")       # "What is quantum computing?"
latest_assistant = state.get_latest_message("assistant")  # "Quantum computing uses qubits..."
missing = state.get_latest_message("system")          # None
```

## Custom State Types

You can subclass `GlobalState` to add domain-specific fields:

```python
from pydantic import Field
from orqest.agents import GlobalState

class ResearchState(GlobalState):
    topic: str = ""
    sources: list[str] = Field(default_factory=list)
    max_depth: int = 3
```

Or use any Pydantic `BaseModel` as your state type. If your state doesn't have a `message_history` attribute, `call_model()` gracefully skips history wiring — it checks with `hasattr` before reading or writing.

## How `call_model()` Wires History

When you call `self.call_model(prompt, state)` inside `_run_implementation()`:

1. **Read**: Gets `state.message_history` (empty list on first call)
2. **Pass**: Calls `self.agent.run(prompt, message_history=state.message_history)`
3. **Process**: pydantic-ai runs any registered history processors (like `keep_recent_messages`)
4. **Store**: After the LLM responds, stores the full updated history back: `state.message_history = result.all_messages()`

On the next call with the same state, step 1 picks up the accumulated history — the LLM sees the full conversation.

## History Processing

### `keep_recent_messages()`

The default history processor truncates old messages while preserving conversation integrity:

- **First message preserved** — always kept, since it typically contains the initial context
- **Sliding window** — keeps the N most recent messages (configured by `truncated_history`)
- **Turn integrity** — if truncation would split a tool-call pair (a `ModelResponse` with a tool call followed by a `ModelRequest` with the tool return), the preceding response is included

```python
# Default: keep 100 most recent messages
agent = MyAgent(..., truncated_history=100)

# Keep only 20 messages for a focused, short-context agent
agent = MyAgent(..., truncated_history=20)
```

### Custom History Processors

Pass your own processors to replace or extend the default behavior:

```python
def only_user_messages(messages):
    """Keep only user prompt messages."""
    return [m for m in messages if hasattr(m, 'parts') and any(
        hasattr(p, 'content') for p in m.parts
    )]

agent = MyAgent(
    ...,
    history_processors=[only_user_messages],
)
```

History processors are callables that take a `list[ModelMessage]` and return a `list[ModelMessage]`. They're passed directly to pydantic-ai's Agent constructor and run before each LLM call.

!!! note
    When you provide custom `history_processors`, the default `keep_recent_messages` is **not** included. Add it explicitly if you want both:

    ```python
    from functools import partial
    from orqest.agents import keep_recent_messages

    agent = MyAgent(
        ...,
        history_processors=[
            my_custom_processor,
            partial(keep_recent_messages, max_messages=50),
        ],
    )
    ```
