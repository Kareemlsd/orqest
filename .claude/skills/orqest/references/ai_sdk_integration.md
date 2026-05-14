# Vercel AI SDK + Orqest Integration

The Polymath demo (`demo/polymath/` in the Orqest repo) wires Vercel AI SDK v6 on the frontend with Orqest's BaseAgent on the backend. This reference is the recipe for replicating that pattern in any Next.js / React consumer.

## Architecture

Two parallel channels between frontend and backend:

```
┌──────────────────┐                    ┌─────────────────────────────┐
│ React Frontend   │                    │ FastAPI Backend             │
│                  │                    │                             │
│  useChat ────────│── Data Stream ────▶│ POST /sessions/{sid}/chat   │
│  (AI SDK v6)     │   Protocol         │   → BaseAgent.call_model    │
│                  │   (chat tokens,    │   → VercelAIAdapter.dispatch│
│                  │   tool calls)      │                             │
│                  │                    │                             │
│  useSidecar ─────│── SSE ────────────▶│ GET /sessions/{sid}/events  │
│  (cognitive      │   (one EventSource │   → sse_sidecar(bus, ...)   │
│   backbone)      │    per session)    │                             │
│                  │                    │                             │
│  ├─ useMetacog.  │                    │                             │
│  ├─ useHealing   │                    │                             │
│  ├─ useUIComps   │                    │                             │
│  └─ useTakeover  │                    │                             │
└──────────────────┘                    └─────────────────────────────┘
```

**The chat stream** is the standard AI SDK v6 path. **The sidecar** is Orqest-specific: it carries the cognitive backbone events (metacognition confidence, healing detections, ui.\<type\> emissions, plan updates, tool activity) on a separate channel so the chat path stays standard.

## Backend setup (FastAPI + Orqest)

### Chat endpoint — Data Stream Protocol

The `VercelAIAdapter` translates an Orqest `BaseAgent` (which wraps a pydantic-ai `Agent`) into AI SDK v6's Data Stream Protocol (`0:"<token>"`, `d:{...}`, `e:{...}` SSE frames).

```python
# backend/app/routes/chat.py
from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.agents.factory import get_polymath_agent  # your BaseAgent factory
from app.runtime.deps import build_state

router = APIRouter()


@router.post("/sessions/{sid}/chat/stream")
async def chat_stream(sid: str, request: Request) -> Response:
    agent = get_polymath_agent()      # cached BaseAgent instance
    deps = build_state(session_id=sid)  # PolymathState or your equivalent
    return await VercelAIAdapter.dispatch_request(
        request,
        agent=agent.agent,             # the underlying pydantic-ai Agent
        deps=deps,
        on_complete=on_complete,       # optional: post-turn hook for self-rating
    )
```

> `VercelAIAdapter` is a Polymath-side helper at `demo/polymath/backend/polymath/vercel_ai_adapter.py`. It is NOT in Orqest core — copy it (or its shape) into your consumer. Open question for v0.3.0: promote it to `orqest.adapters.vercel`.

The pattern adapter accepts pydantic-ai `Agent.run_stream()` events and re-encodes them as AI SDK v6 frames.

### Hydration endpoint

For chat reload, ship a separate `GET /sessions/{sid}/messages` that returns the persisted message log. The frontend hydrates `useChat`'s state on mount.

```python
@router.get("/sessions/{sid}/messages")
async def get_messages(sid: str) -> list[UIMessage]:
    # Query your persistence layer
    return await db.get_messages(sid)
```

`UIMessage` matches the AI SDK shape: `{id, role, parts}` where parts are `{type: "text" | "tool-call" | ..., ...}`.

### SSE sidecar — cognitive backbone

A separate route exposes the Orqest `EventBus` as Server-Sent Events. The frontend opens one `EventSource` per session.

```python
# backend/app/routes/events.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from orqest.observability import sse_sidecar

router = APIRouter()


@router.get("/sessions/{sid}/events")
async def stream_events(sid: str) -> StreamingResponse:
    runtime = get_runtime(sid)         # your session-runtime cache
    wb = runtime.workbench             # one Workbench per session
    replay = list(wb.recent_events)    # ring-buffered last N events for reconnect catch-up
    return StreamingResponse(
        sse_sidecar(wb.event_bus, replay=replay, heartbeat_s=15.0),
        media_type="text/event-stream",
    )
```

### Per-session Workbench wiring

Each session gets a fresh `Workbench` bundling memory + tracer + bus + ring buffer.

```python
# backend/app/runtime/workbench_factory.py
from orqest.workbench import Workbench
from orqest.observability import EventBus, EventBusPublishHook
from orqest.hooks import HookRunner
from orqest.memory import LocalMemoryStore
from orqest.metacognition import MetacognitionHook
from orqest.healing import HealingConfig

_runtimes: dict[str, "SessionRuntime"] = {}


def get_runtime(session_id: str) -> "SessionRuntime":
    if session_id not in _runtimes:
        memory = LocalMemoryStore("/var/app/memory.db")
        bus = EventBus()
        workbench = Workbench(memory=memory, event_bus=bus)

        hook_runner = HookRunner(hooks=[
            EventBusPublishHook(bus),
            MetacognitionHook(bus=bus),
        ])

        if os.getenv("ENABLE_HEALING") == "1":
            healing = workbench.with_healing(
                HealingConfig(...),
                api_key={"openai": ..., "anthropic": ...},
            )
        else:
            healing = None

        _runtimes[session_id] = SessionRuntime(
            workbench=workbench,
            hook_runner=hook_runner,
            healing=healing,
        )
    return _runtimes[session_id]
```

Healing is started lazily on the first chat request via `runtime.ensure_started()` (so import-time cost is zero).

## Frontend setup (React + AI SDK v6)

### Dependencies

```jsonc
{
  "dependencies": {
    "ai": "^6.0.0",
    "@ai-sdk/react": "^3.0.0",
    "react": "^19.0.0",
    "next": "^16.0.0"
  }
}
```

### useChat hook

`DefaultChatTransport` handles Data Stream Protocol decoding. Pass `headers` to inject session id or auth.

```typescript
// frontend/src/hooks/useChat.ts
import { DefaultChatTransport } from "ai";
import { useChat as useChatSDK } from "@ai-sdk/react";
import { useMemo, useRef } from "react";


export function useChat(sessionId: string, base: string) {
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `${base}/sessions/${sessionId}/chat/stream`,
        headers: () => ({ "X-Session-Id": sessionIdRef.current }),
      }),
    [base, sessionId],
  );

  const { messages, sendMessage, status, error, stop, setMessages } = useChatSDK({
    transport,
  });

  // Hydrate from server on mount (optional — for reload-friendly UX)
  useEffect(() => {
    fetch(`${base}/sessions/${sessionId}/messages`)
      .then((r) => r.json())
      .then((m) => setMessages(m));
  }, [sessionId, base, setMessages]);

  return { messages, sendMessage, status, error, stop };
}
```

### Sidecar provider — one EventSource per session

The sidecar is the dispatch hub. All cognitive-backbone hooks subscribe through it. Don't open a separate `EventSource` per hook.

```typescript
// frontend/src/hooks/useSidecar.ts (see assets/frontend_hooks/useSidecar.ts for the full file)
import { createContext, useContext, useEffect, useRef } from "react";


export type AgentEvent = {
  event_type: string;
  agent_name: string;
  timestamp: string;
  data: Record<string, unknown>;
  span_id?: string;
  trace_id?: string;
};


type Subscriber = (evt: AgentEvent) => void;

const SidecarCtx = createContext<{
  subscribeAll: (fn: Subscriber) => () => void;
}>({ subscribeAll: () => () => {} });


export function SidecarProvider({ sessionId, base, children }: {
  sessionId: string;
  base: string;
  children: React.ReactNode;
}) {
  const subscribers = useRef(new Set<Subscriber>());
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const src = new EventSource(`${base}/sessions/${sessionId}/events`);
    sourceRef.current = src;
    src.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as AgentEvent;
        for (const sub of subscribers.current) sub(evt);
      } catch {}
    };
    return () => { src.close(); sourceRef.current = null; };
  }, [sessionId, base]);

  return (
    <SidecarCtx.Provider value={{
      subscribeAll: (fn) => {
        subscribers.current.add(fn);
        return () => subscribers.current.delete(fn);
      },
    }}>
      {children}
    </SidecarCtx.Provider>
  );
}


export function useSidecar(sessionId: string, handler: Subscriber) {
  const { subscribeAll } = useContext(SidecarCtx);
  useEffect(() => subscribeAll(handler), [subscribeAll, handler]);
}
```

### Metacognition badge

Subscribes to `metacognition.confidence` and freezes the frame onto the current assistant message id (first-write-wins).

```typescript
// frontend/src/hooks/useMetacognition.ts (see assets/frontend_hooks/useMetacognition.ts)
import { useCallback, useRef, useState } from "react";
import { useSidecar, type AgentEvent } from "./useSidecar";


export function useMetacognition(sessionId: string, currentAssistantId: string | null) {
  const [frames, setFrames] = useState(new Map<string, ConfidenceFrame>());
  const currentIdRef = useRef(currentAssistantId);
  currentIdRef.current = currentAssistantId;

  const handler = useCallback((evt: AgentEvent) => {
    if (evt.event_type !== "metacognition.confidence") return;
    const targetId = currentIdRef.current;
    if (!targetId) return;
    setFrames((prev) => {
      if (prev.has(targetId)) return prev;  // first-write-wins
      const next = new Map(prev);
      next.set(targetId, {
        confidence: evt.data.confidence as number,
        uncertaintyTargets: evt.data.uncertainty_targets as string[],
        capabilityBoundary: evt.data.capability_boundary as boolean,
        protocol: evt.data.protocol_name as string,
      });
      return next;
    });
  }, []);

  useSidecar(sessionId, handler);

  return { frames };
}
```

The id-keying pattern is critical: backend `ModelResponse.id` does NOT match the frontend's `UIMessage.id`. Do not key by backend id. **Key by the message id you control on the frontend at the moment the event arrives.**

### Healing toasts

```typescript
// frontend/src/hooks/useHealingEvents.ts (see assets/frontend_hooks/useHealingEvents.ts)
import { useCallback, useState } from "react";
import { useSidecar, type AgentEvent } from "./useSidecar";


type HealingEntry = { id: string; kind: string; summary: string; ts: number };


export function useHealingEvents(sessionId: string, maxItems = 24) {
  const [entries, setEntries] = useState<HealingEntry[]>([]);

  const handler = useCallback((evt: AgentEvent) => {
    if (!evt.event_type.startsWith("healing.")) return;
    const projected = projectEvent(evt);
    if (!projected) return;
    setEntries((prev) => {
      const next = [projected, ...prev];
      if (next.length > maxItems) next.length = maxItems;
      return next;
    });
  }, [maxItems]);

  useSidecar(sessionId, handler);

  return { entries, dismiss: (id: string) => setEntries((p) => p.filter((e) => e.id !== id)) };
}


function projectEvent(evt: AgentEvent): HealingEntry | null {
  switch (evt.event_type) {
    case "healing.detection":
      return { id: evt.timestamp, kind: "detection", summary: evt.data.summary as string, ts: Date.now() };
    case "healing.retry_initiated":
      return { id: evt.timestamp, kind: "retry", summary: evt.data.tool_name as string, ts: Date.now() };
    case "healing.model_fallback":
      return { id: evt.timestamp, kind: "fallback", summary: `${evt.data.from} → ${evt.data.to}`, ts: Date.now() };
    case "healing.model_chain_exhausted":
      return { id: evt.timestamp, kind: "exhausted", summary: "fallback chain exhausted", ts: Date.now() };
    default:
      return null;
  }
}
```

### Generative UI components

Subscribes to `ui.<componentType>.{init,delta,remove}` events and projects them into a registry. Renderers resolve by `component_type`.

```typescript
// frontend/src/hooks/useUIComponents.ts (see assets/frontend_hooks/useUIComponents.ts)
import { useCallback, useState } from "react";
import { useSidecar, type AgentEvent } from "./useSidecar";


type UIComponentSpec<T = unknown> = {
  component_type: string;
  component_id: string;
  data: T;
  metadata: Record<string, unknown>;
  created_at: string;
};


export function useUIComponents<T = unknown>(
  sessionId: string,
  componentType: string,
) {
  const [byId, setById] = useState<Map<string, UIComponentSpec<T>>>(new Map());

  const initType = `ui.${componentType}.init`;
  const deltaType = `ui.${componentType}.delta`;
  const removeType = `ui.${componentType}.remove`;

  const handler = useCallback((evt: AgentEvent) => {
    if (evt.event_type === initType) {
      const spec = evt.data as UIComponentSpec<T>;
      setById((prev) => new Map(prev).set(spec.component_id, spec));
    } else if (evt.event_type === deltaType) {
      const { component_id, op, path, value } = evt.data as {
        component_id: string;
        op: "replace" | "merge" | "append" | "remove";
        path: string;
        value: unknown;
      };
      setById((prev) => {
        const spec = prev.get(component_id);
        if (!spec) return prev;
        const next = new Map(prev);
        next.set(component_id, applyDelta(spec, op, path, value));
        return next;
      });
    } else if (evt.event_type === removeType) {
      const { component_id } = evt.data as { component_id: string };
      setById((prev) => {
        const next = new Map(prev);
        next.delete(component_id);
        return next;
      });
    }
  }, [initType, deltaType, removeType]);

  useSidecar(sessionId, handler);

  return { components: Array.from(byId.values()) };
}


function applyDelta<T>(spec: UIComponentSpec<T>, op: string, path: string, value: unknown): UIComponentSpec<T> {
  // dot-path navigation; immutable update; see assets/frontend_hooks/useUIComponents.ts
  // for the full implementation
  return spec;
}
```

The dot-path mutation logic is non-trivial — copy the full implementation from `assets/frontend_hooks/useUIComponents.ts`.

### Renderer registry

The frontend maintains a `component_type → React component` registry. Polymath ships 12 built-in renderers (`markdown`, `vega_chart`, `mermaid`, `latex`, `json_viewer`, `sandboxed_html`, `layout`, `text`, `image`, `badge`, `button`, `input`).

```typescript
// frontend/src/components/ui-renderers/registry.ts
import { MarkdownRenderer } from "./MarkdownRenderer";
import { VegaChartRenderer } from "./VegaChartRenderer";
// ... etc

export const renderers: Record<string, React.ComponentType<{ spec: any }>> = {
  markdown: MarkdownRenderer,
  vega_chart: VegaChartRenderer,
  // ...
};


export function UIComponentRenderer({ spec }: { spec: { component_type: string; data: unknown } }) {
  const Renderer = renderers[spec.component_type];
  if (!Renderer) return <div>Unknown component: {spec.component_type}</div>;
  return <Renderer spec={spec} />;
}
```

Custom renderers register the same way: import + add to the map. Backend-side, the `ComponentRegistry` validates the typed payload before emit.

### TakeoverDialog modal

When the agent emits a `TakeoverDialogComponent`, surface a modal. User response POSTs back to a route the agent's loop awaits.

```typescript
// frontend/src/components/TakeoverDialogModal.tsx (sketch)
import { useUIComponents } from "@/hooks/useUIComponents";


export function TakeoverDialogModal({ sessionId }: { sessionId: string }) {
  const { components } = useUIComponents<TakeoverDialogData>(sessionId, "takeover_dialog");
  const dialog = components[0];
  if (!dialog) return null;

  const respond = async (response: unknown) => {
    await fetch(`/sessions/${sessionId}/takeover/respond`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ component_id: dialog.component_id, response }),
    });
  };

  return <Dialog>{/* render dialog.data; call respond on user choice */}</Dialog>;
}
```

The backend route consumes the response and emits a `takeover.responded` event the agent loop awaits before proceeding. (Polymath has the modal; the response endpoint is forward-compat — wire it on demand.)

## Common pitfalls

- **Don't open a separate EventSource per hook.** Browsers cap concurrent connections per origin. Use a `SidecarProvider` at the session root and have hooks subscribe via context.
- **Don't key metacognition events by backend message id.** It does not match the AI SDK's `UIMessage.id`. Key by the *current* assistant message id at event-arrival time.
- **Don't ship Polymath's `VercelAIAdapter` verbatim if your agent's output type is non-string.** The adapter assumes streaming text; for typed structured output, use `agent.run_stream()` directly and emit the final result as a single `data` event.
- **Don't expose `sse_sidecar` without auth.** It carries cognitive-backbone events that can include tool input/output previews. Gate the route by the same auth as the chat endpoint.
- **Don't trust the SSE replay buffer to hold everything.** It's a ring buffer (default 200 events). For audit, persist events to your existing observability layer in parallel via a `subscribe_all` handler.

## Going further

- **Custom UI components:** subclass `UIComponentSpec[T]` on the backend, register in the `ComponentRegistry`, add a renderer on the frontend keyed by `component_type`.
- **Persistent message store:** the AI SDK's `setMessages` rehydrates from any source — point it at your existing message table. Polymath uses a separate `messages` table keyed by session.
- **Auth on the SSE channel:** `EventSource` doesn't support custom headers natively. Either short-poll a session token cookie, or use a fetch-based SSE polyfill (`@microsoft/fetch-event-source`) that does support headers.
- **Cancellation:** `useChat`'s `stop()` aborts the current chat stream. To also stop sidecar emissions (cancel a long-running tool), POST a `cancel` event to a backend route that calls into the running agent run via `pydantic_ai`'s cancellation mechanism.

## Where Polymath does it

Reference paths in the Orqest repo:

- Backend chat: `demo/polymath/backend/polymath/routers/chat.py`
- Backend SSE sidecar: `demo/polymath/backend/polymath/routers/events.py`
- Backend Workbench wiring: `demo/polymath/backend/polymath/workbench_factory.py`
- Frontend useChat: `demo/polymath/frontend/src/hooks/useChat.ts`
- Frontend sidecar: `demo/polymath/frontend/src/hooks/useSidecar.ts` (or similar — verify in repo)
- Frontend metacognition: `demo/polymath/frontend/src/hooks/useMetacognition.ts`
- Frontend healing: `demo/polymath/frontend/src/hooks/useHealingEvents.ts`
- Frontend UI components: `demo/polymath/frontend/src/hooks/useUIComponents.ts`
- Renderer registry: `demo/polymath/frontend/src/components/ui-renderers/`

When in doubt, read Polymath's hooks and copy them. They're battle-tested.
