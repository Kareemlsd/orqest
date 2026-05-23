# Session Persistence

`BaseSessionState` extends `GlobalState` with session tracking and JSON-safe serialization, enabling cross-session persistence.

## BaseSessionState

```python
import asyncio
from orqest.agents import BaseSessionState


async def main():
    # Create a session
    state = BaseSessionState()
    state.add_message("user", "Hello")
    state.add_message("assistant", "Hi there!")

    print(state.session_id)   # auto-generated UUID
    print(state.created_at)   # timestamp

    # Serialize to JSON-safe dict
    data = state.serialize()

    # Restore from serialized data (e.g., from a database)
    restored = BaseSessionState.deserialize(data)
    print(restored.session_id == state.session_id)  # True
    print(restored.messages)  # [{"role": "user", ...}, {"role": "assistant", ...}]


asyncio.run(main())
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `session_id` | `str` | Auto-generated UUID | Unique session identifier |
| `created_at` | `datetime` | `datetime.now()` | Session creation timestamp |
| `messages` | `list[dict]` | `[]` | Application-level message log (inherited from `GlobalState`) |
| `message_history` | `list[ModelMessage]` | `[]` | pydantic-ai message objects (inherited from `GlobalState`) |

## Serialization

The `serialize()` method handles pydantic-ai `ModelMessage` objects, which are dataclasses (not Pydantic models) and require special handling via `ModelMessagesTypeAdapter`:

```python
data = state.serialize()
# data is a plain dict safe for JSON, database storage, etc.
# message_history is serialized via pydantic-ai's ModelMessagesTypeAdapter
```

## Deserialization and Corrupt Data Resilience

`deserialize()` gracefully handles corrupt or missing `message_history`:

```python
# Corrupt data won't crash — falls back to empty history
state = BaseSessionState.deserialize({
    "session_id": "abc",
    "created_at": "2025-01-01T00:00:00",
    "messages": [],
    "message_history": "this is not valid",  # corrupt
})
# state.message_history == []  (fallback, logged as warning)
```

This resilience is intentional -- `message_history` is a boundary where external JSON may be malformed.

## Subclassing with Custom Fields

Add domain-specific fields by subclassing:

```python
from pydantic import Field
from orqest.agents import BaseSessionState


class ResearchSession(BaseSessionState):
    topic: str = ""
    sources: list[str] = Field(default_factory=list)
    iteration_count: int = 0


# Serialization includes custom fields automatically
session = ResearchSession(topic="quantum computing")
session.sources.append("arxiv.org/123")
data = session.serialize()

restored = ResearchSession.deserialize(data)
print(restored.topic)    # "quantum computing"
print(restored.sources)  # ["arxiv.org/123"]
```

## What's Happening Under the Hood

**`serialize()`:**

1. Calls `model_dump(exclude={"message_history"})` to serialize all Pydantic fields
2. Separately serializes `message_history` via `ModelMessagesTypeAdapter.dump_python(..., mode="json")`
3. Merges both into a single dict

**`deserialize()`:**

1. Pops `message_history` from the raw dict
2. Attempts to validate it via `ModelMessagesTypeAdapter.validate_python()`
3. On failure, logs a warning and falls back to an empty list
4. Constructs the instance with the validated history and remaining fields

## Related Concepts

- [State & History](state-and-history.md) -- `GlobalState` that `BaseSessionState` extends
- [Compound Tools](compound-tools.md) -- often used with session state for stateful tool patterns
