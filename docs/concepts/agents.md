# Agents

`BaseAgent[StateT, OutputT]` is the abstract foundation for all orqest agents. It's generic over two type parameters:

- **`StateT`** — the input state (must be a Pydantic `BaseModel`)
- **`OutputT`** — the structured output (must be a Pydantic `BaseModel`)

## Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_name` | `str` | required | Name for logging and identification |
| `system_prompt` | `str` | required | System prompt guiding agent behavior |
| `output_type` | `type[OutputT]` | required | Pydantic model class for structured output |
| `model` | `Model \| str` | required | A pydantic-ai `Model` instance or `'provider:model_id'` string |
| `api_key` | `str \| None` | `None` | Required when `model` is a string |
| `retries` | `int` | `3` | Retry attempts for failed LLM calls |
| `tools` | `list[Tool] \| None` | `None` | Individual `Tool` instances to register |
| `toolsets` | `list[Any] \| None` | `None` | Toolset objects providing collections of tools |
| `truncated_history` | `int` | `100` | Max recent messages for the default history processor |
| `history_processors` | `list \| None` | `None` | Custom processors; defaults to `keep_recent_messages` |
| `model_settings` | `ModelSettings \| None` | `None` | pydantic-ai `ModelSettings` applied to every model call |
| `reasoning` | `ReasoningEffort \| None` | `None` | Provider-agnostic reasoning/thinking effort — see below |

The `model` parameter can be provided in two ways:

```python
# Option 1: String format (most common)
agent = MyAgent(..., model="openai:gpt-4.1", api_key="sk-...")

# Option 2: Pre-built pydantic-ai Model instance
from orqest.utils.llm_model import resolve_model
model = resolve_model("openai:gpt-4.1", api_key="sk-...")
agent = MyAgent(..., model=model)
```

## Output type constraints

`output_type` must be a Pydantic `BaseModel` subclass (or a scalar like `str`/`int`). At agent construction, `BaseAgent` inspects the model's fields and rejects any field annotated as top-level `Any` — most LLM providers (OpenAI in particular) reject such schemas at first inference with the opaque `Invalid schema for function 'final_result'` 400 error and no breadcrumb. Catching it eagerly saves debugging time.

```python
from typing import Any
from pydantic import BaseModel
from orqest.agents import BaseAgent

class BadOutput(BaseModel):
    text: str
    payload: Any  # ← top-level Any, will be rejected

agent = MyAgent(output_type=BadOutput, ...)
# raises BaseAgentSchemaError naming 'payload' as the offending field
```

What's accepted:

- Concrete types: `str`, `int`, `bool`, `float`, lists/dicts of concrete types, Pydantic models, discriminated unions, `Literal[...]`.
- **Containers** holding `Any`: `list[Any]`, `dict[str, Any]` — these serialize to typed arrays/objects and are accepted by providers. Only top-level `Any` is the killer.
- Scalar output types: `output_type=str` etc. — skips the check entirely.

If you genuinely need a free-form payload, the standard pattern is `field: str` carrying a JSON blob you parse downstream — keeps the schema concrete for the provider while preserving flexibility.

## Reasoning / thinking

Modern LLMs can spend extra tokens "thinking" before they answer. Each provider exposes
this differently — Anthropic uses a thinking-token budget, OpenAI uses a categorical
reasoning effort, Google uses a thinking config, OpenRouter uses a reasoning object. The
`reasoning` parameter collapses all of that into one provider-agnostic knob:

```python
agent = MyAgent(
    ...,
    model="anthropic:claude-sonnet-4-6",
    api_key="sk-...",
    reasoning="high",
)
```

`reasoning` accepts one of `"minimal"`, `"low"`, `"medium"`, `"high"`. Orqest translates it
to the right provider-specific `ModelSettings` key — keyed off the same `provider:` prefix
`resolve_model()` uses — and merges it into `model_settings`:

| Provider | Translated to |
|----------|---------------|
| `openai` | `openai_reasoning_effort` (categorical, passed through) |
| `anthropic` | `anthropic_thinking` with a `budget_tokens` derived from the effort |
| `google` | `google_thinking_config` with a `thinking_budget` derived from the effort |
| `openrouter` | `openrouter_reasoning` (`"minimal"` collapses to `"low"`) |

For the budget-based providers (Anthropic, Google), orqest also fills a sensible `max_tokens`
when you haven't set one — Anthropic *requires* `max_tokens` to exceed the thinking budget,
so reasoning works out of the box. If you pass `model_settings` with explicit keys, those win
on conflict; `reasoning` only fills what you left unset.

!!! note "The model must support reasoning"
    `reasoning` translates the setting — it does not check that your chosen model is a
    reasoning-capable one. Pair it with a model that actually supports thinking (e.g. a
    Claude Sonnet/Opus, an OpenAI o-series or GPT-5 model, a Gemini 2.5 model). The model's
    provider must be one orqest can resolve, or construction raises `ValueError`.
    Effort-value support also varies *by model* — the `"minimal"` … `"high"` vocabulary is
    the union across providers, and not every model accepts every level (OpenAI's `gpt-5.2`,
    for instance, accepts `"low"` / `"medium"` / `"high"` but rejects `"minimal"`). An
    unsupported value surfaces as a provider error at call time, not at construction.

## Implementing `_run_implementation()`

This is the one method you must override. It receives the state and must return an instance of `OutputT`:

```python
class MyAgent(BaseAgent[GlobalState, MyOutput]):
    async def _run_implementation(self, state: GlobalState, **kwargs) -> MyOutput:
        user_message = state.get_latest_message("user")
        result = await self.call_model(user_message, state)
        return result.output
```

The pattern is straightforward:

1. Extract what you need from `state`
2. Call the LLM via `self.call_model()` or `self.agent.run()`
3. Return the structured output

## `call_model()` vs `self.agent.run()`

`BaseAgent` provides two ways to invoke the LLM:

### `call_model(prompt, state)` — Stateful (recommended)

Automatically manages conversation history:

1. Reads `state.message_history` and passes it to the LLM
2. Stores the updated history back on `state` after the call
3. Returns the full `AgentRunResult` (access `.output`, `.all_messages()`, `.new_messages()`)

```python
async def _run_implementation(self, state, **kwargs):
    result = await self.call_model("Analyze this text", state)
    return result.output
```

Use this when you want multi-turn conversations where the agent remembers prior context.

#### Multi-modal prompts

All `BaseAgent` methods that accept a `prompt` support multi-modal input. Pass a list mixing text and content objects instead of a plain string:

```python
from pydantic_ai import ImageUrl, DocumentUrl, BinaryContent

# URL-based image
result = await self.call_model(
    ["Describe this image:", ImageUrl(url="https://example.com/photo.jpg")],
    state,
)

# URL-based PDF document
result = await self.call_model(
    ["Summarize:", DocumentUrl(url="https://example.com/report.pdf")],
    state,
)

# Local file via BinaryContent
content = BinaryContent.from_path("chart.png")
result = await self.call_model(["Analyze this chart:", content], state)

# Mixed content
result = await self.call_model(
    [
        "Compare the image with the document:",
        ImageUrl(url="https://example.com/diagram.png"),
        DocumentUrl(url="https://example.com/spec.pdf"),
    ],
    state,
)
```

The available content types (from `pydantic_ai`) are:

| Type | Use case |
|------|----------|
| `ImageUrl` | URL-referenced images (JPEG, PNG, GIF, WebP) |
| `AudioUrl` | URL-referenced audio (MP3, WAV, FLAC, etc.) |
| `VideoUrl` | URL-referenced video (MP4, MKV, WebM, etc.) |
| `DocumentUrl` | URL-referenced documents (PDF, TXT, CSV, DOCX, etc.) |
| `BinaryContent` | Raw bytes with media type — works with any modality |

!!! note "Provider support varies"
    Not all providers support all modalities. For example, Anthropic supports images and PDFs but not audio or video. Check your provider's documentation for details.

### `self.agent.run(prompt)` — Stateless

Calls the pydantic-ai agent directly with no history management:

```python
async def _run_implementation(self, state, **kwargs):
    result = await self.agent.run("Analyze this text")
    return result.output
```

Use this for one-shot tasks where conversation history isn't needed. The [agent-as-tool](agent-as-tool.md) pattern uses this approach implicitly.

## Streaming

`BaseAgent` also provides streaming variants of `call_model()` for real-time output. See the [Streaming](streaming.md) page for full details.

- **`stream_output(prompt, state)`** — async generator yielding partial `OutputT` instances as the LLM generates tokens
- **`stream_events(prompt, state)`** — async generator yielding `AgentStreamEvent` instances, including tool call and result events
- **`call_model_stream(prompt, state)`** — async context manager yielding the raw `StreamedRunResult` for full control

All streaming methods manage `state.message_history` identically to `call_model()`.

## Lazy Agent Construction

The underlying pydantic-ai `Agent` is created on first access to `self.agent`. This means:

- You can inspect or modify `self.tools` and `self.toolsets` after `__init__` and before the first `run()` call
- The pydantic-ai Agent is a singleton per `BaseAgent` instance — subsequent accesses return the same object

## Tools and Toolsets

Register tools through the constructor:

```python
from pydantic_ai import Tool

def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Sunny in {city}"

agent = MyAgent(
    ...,
    tools=[Tool(get_weather)],
)
```

See the [pydantic-ai documentation](https://ai.pydantic.dev/tools/) for details on creating tools and toolsets.
