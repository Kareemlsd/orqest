# SSE Sidecar — stream AgentEvents to a browser

Many Orqest apps need a "side channel" that pushes observability data
(plan updates, memory recalls, trace spans) to the frontend without
cluttering the main chat stream. `sse_sidecar` subscribes to an
`EventBus` and produces SSE-formatted chunks you can hand straight to
any ASGI framework's streaming response.

The result: a single `/events` endpoint that streams everything a
long-running agent is doing, decoupled from the chat protocol and
immune to the Vercel AI data-stream shape.

## Minimal FastAPI integration

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from orqest.observability import EventBus, sse_sidecar

app = FastAPI()
bus = EventBus()  # shared with your agent's HookRunner


@app.get("/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        sse_sidecar(bus, heartbeat_s=15.0),
        media_type="text/event-stream",
    )
```

On the browser side, a plain `EventSource('/events')` receives one
message per `AgentEvent`. The SSE `event:` field holds
`AgentEvent.event_type`, the `data:` field holds a JSON payload.

## Replay on reconnect

Pass `replay=[...]` to emit historical events before live streaming
starts — useful for refresh/reload scenarios where the client has lost
its in-memory view.

```python
from collections import deque

buffer: deque[AgentEvent] = deque(maxlen=200)
bus.subscribe_all(buffer.append)

@app.get("/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        sse_sidecar(bus, replay=list(buffer)),
        media_type="text/event-stream",
    )
```

## Heartbeats + backpressure

- `heartbeat_s` (default 15.0) emits an SSE comment line every N
  seconds of idle time. Prevents proxies from closing the stream.
- `queue_size` (default 256) caps in-flight events per consumer. When
  a slow consumer fills the queue, the oldest event is dropped to
  make room for the newest — the stream never stalls the publisher.

## Reference

::: orqest.observability.sse_sidecar
