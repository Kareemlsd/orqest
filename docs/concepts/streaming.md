# Streaming

Streaming lets users see results as the LLM generates them — essential for responsive UIs and real-time API endpoints. Instead of waiting for the full response, you receive partial output that progressively fills in.

## Three Streaming Primitives

`BaseAgent` provides three streaming methods that mirror `call_model()` but yield results incrementally:

| Method | Level | Returns | Tool visibility |
|--------|-------|---------|-----------------|
| `stream_output(prompt, state)` | High | Async generator of `OutputT` partials | Hidden |
| `stream_events(prompt, state)` | High | Async generator of `AgentStreamEvent` | **Visible** |
| `call_model_stream(prompt, state)` | Low | `StreamedRunResult` context manager | Hidden |

All three manage `state.message_history` identically to `call_model()` — history is updated after the stream is consumed.

## `stream_output()` — Structured Output Streaming

An async generator that yields partial `OutputT` Pydantic model instances. Each yield is a progressively more complete version of the structured output:

```python
async for partial in agent.stream_output(prompt, state, debounce_by=0):
    # partial is an OutputT instance with fields filling in
    print(f"Title so far: {partial.title}")
    print(f"Findings: {len(partial.key_findings)} items")
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | `str` | required | The user prompt to send |
| `state` | `StateT` | required | Conversation state — history is read and updated |
| `debounce_by` | `float \| None` | `None` | Minimum interval (seconds) between yields. Use `0` for maximum granularity |

History is updated after the generator is fully consumed (the `async for` loop completes).

## `stream_events()` — Full Event Streaming with Tool Visibility

An async generator that yields `AgentStreamEvent` instances — including model response tokens **and** tool call/result events. This uses pydantic-ai's `Agent.iter()` under the hood for full node-by-node control.

```python
async for event in agent.stream_events(prompt, state):
    if event.event_kind == "function_tool_call":
        print(f"Calling tool: {event.part.tool_name}")
    elif event.event_kind == "function_tool_result":
        print(f"Tool returned: {event.result.content}")
    elif event.event_kind == "final_result":
        print("Output schema matched — generating final output")
```

### Event Types

| Event kind | Type | Description |
|------------|------|-------------|
| `part_start` | `PartStartEvent` | A new response part begins (text or tool call) |
| `part_delta` | `PartDeltaEvent` | Incremental token(s) for a part |
| `part_end` | `PartEndEvent` | A response part is fully received |
| `final_result` | `FinalResultEvent` | Output schema matched |
| `function_tool_call` | `FunctionToolCallEvent` | A tool is about to be called |
| `function_tool_result` | `FunctionToolResultEvent` | A tool returned a result |

Use this when you need to show the agent's reasoning process in a UI: "Calling API..." → "Got result" → "Generating response..."

## `call_model_stream()` — Low-Level Context Manager

An async context manager that yields the raw `StreamedRunResult` from pydantic-ai. Use this when you need direct access to the stream — for example, to read metadata or use `stream_responses()`:

```python
async with agent.call_model_stream(prompt, state) as streamed:
    print(f"Run ID: {streamed.run_id}")
    output = await streamed.get_output()
```

The `StreamedRunResult` provides:

- `stream_output()` — validated partial outputs (same as the high-level method)
- `stream_responses()` — raw `ModelResponse` objects with `debounce_by` control
- `get_output()` — consume the stream and return the final validated output
- `all_messages()` — full message history after consumption

History is updated when the context manager exits.

## Multi-Turn Streaming

Streaming methods wire history the same way `call_model()` does. You can freely mix streaming and non-streaming calls:

```python
state = GlobalState()

# Turn 1 — non-streaming
state.add_message("user", "Analyze this report...")
result = await agent.call_model(state.get_latest_message("user"), state)

# Turn 2 — streaming (agent sees full history from turn 1)
state.add_message("user", "Now focus on the financials.")
async for partial in agent.stream_output(state.get_latest_message("user"), state):
    print(partial)
```

## Transport Integration

Because `stream_output()` and `stream_events()` are plain async generators, they plug into any async transport:

### FastAPI SSE

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.post("/analyze/stream")
async def analyze_stream(text: str):
    state = GlobalState()
    state.add_message("user", text)

    async def event_generator():
        async for partial in agent.stream_output(
            state.get_latest_message("user"), state, debounce_by=0.05
        ):
            yield f"data: {partial.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
```

### WebSockets

```python
@app.websocket("/ws/analyze")
async def ws_analyze(websocket: WebSocket):
    await websocket.accept()
    text = await websocket.receive_text()

    state = GlobalState()
    state.add_message("user", text)

    async for partial in agent.stream_output(
        state.get_latest_message("user"), state
    ):
        await websocket.send_json(partial.model_dump())

    await websocket.close()
```

orqest stays transport-agnostic — the streaming methods produce data, you choose how to deliver it.
