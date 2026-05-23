# Orqest Demo

Runnable showcase of the Orqest framework. Two things live here:

1. **The Workbench** (`/workbench`) — the **canonical UI template** for any
   Orqest-powered application. Copy this as the starting point for new apps.
2. **Five focused demos** (`/demos/*`) — each isolates one UI pattern for
   study (streaming chat, artifact preview, task tree, multimodal, research).

---

## Quick start

Two processes:

```bash
# Terminal 1 — backend
cd ~/repos/orqest
PYTHONPATH=. .venv/bin/uvicorn demo.backend.server:app --port 8000

# Terminal 2 — frontend
cd ~/repos/orqest/demo/frontend
npm run dev
```

Open `http://localhost:3000/workbench`.

---

## The Workbench — the template you copy

The Workbench is the reference implementation of an Orqest-powered app.
It demonstrates every Orqest primitive in a single cohesive UI:

| Primitive | Where |
|---|---|
| `LocalMemoryStore` (SQLite + FTS5) | `demo/backend/workbench/state.py` |
| `JSONTracer` span recording | `demo/backend/workbench/agent.py` → `start_agent_run_span` |
| `EventBus` lifecycle events | `demo/backend/workbench/state.py` → `event_bus.subscribe_all` |
| Tool orchestration (7 tools) | `demo/backend/workbench/agent.py` |
| `VercelAIAdapter.dispatch_request` streaming | `demo/backend/workbench/router.py` |
| Sidecar polling for memory/trace/events | `demo/frontend/src/app/workbench/page.tsx` → `fetchSidecar` |
| Contextual right-panel tabs (Artifact, Tasks, Sources, Memory, Trace, Events) | same file |

### Layout architecture

Three-zone shell — the pattern that reference implementations like
Claude Code Desktop, Manus, Cursor, and ChatGPT Canvas all converged on:

```
┌─────────┬────────────────────────────┬────────────────────────┐
│ Sidebar │ Chat (primary anchor)      │ Contextual right panel │
│ Nav +   │  - streaming text          │ Tabs:                  │
│ featured│  - inline tool cards       │  Artifact / Tasks /    │
│ links   │  - inline stubs for panels │  Sources / Memory /    │
│         │  - hairline stream bar     │  Trace / Events        │
│         ├────────────────────────────┤                        │
│         │ PromptInput                │                        │
└─────────┴────────────────────────────┴────────────────────────┘
```

**Why this layout**:
- Chat stays the anchor — the user never loses the conversation
- Right-panel tabs swap context without navigating away
- Inline stubs for artifacts / plans / memory writes let the chat stay readable
  while the full view lives in the right panel (click stub → focus that tab)
- Auto-focus the relevant tab when a new artifact or plan arrives

### Agent pattern

The agent is a plain `pydantic_ai.Agent` — Orqest stays in the infrastructure
(memory, tracing, events), not in the agent. This is the key to the
architecture: pydantic-ai does what it's good at; Orqest makes everything
around it production-grade.

Every tool call emits an `AgentEvent` on the EventBus:

```python
async def remember(content: str, category: str = "general") -> str:
    entry = MemoryEntry(
        content=content,
        memory_type="episodic",
        source_agent="workbench",
        metadata={"category": category},
    )
    await memory.store(entry)
    await _emit("memory:stored", {"id": entry.id, "content": content})
    return f"Stored memory: {content}"
```

The frontend polls `/api/workbench/state` (every 1s while streaming, 4s idle)
to snapshot memory/trace/events into React state.

### Structured output for UI panels

Rather than parse free-form agent output, the agent is given explicit tools
whose args ARE the UI payload:

```python
# emit_plan(goal, steps) → Tasks tab
# emit_artifact(title, language, code) → Artifact tab
```

The frontend pulls these from `message.parts` by `part.type === "tool-emit_plan"`
and renders them in the right panel. This is the cleanest way to drive rich UI
from an LLM — no regex parsing, no fragile formats, just well-typed tool args.

---

## File map

```
demo/
├── backend/
│   ├── _config.py              # Shared config (MODEL, API key setup)
│   ├── server.py               # FastAPI app; mounts all routers
│   ├── tools.py                # Shared mock tools (search, time, calc)
│   ├── demos/                  # Focused demos (one pattern each)
│   │   ├── chat.py
│   │   ├── artifact.py
│   │   ├── tasks.py            # structured output via pydantic-ai
│   │   ├── multimodal.py
│   │   └── research.py
│   └── workbench/              # THE CANONICAL APP
│       ├── state.py            # LocalMemoryStore + JSONTracer + EventBus
│       ├── agent.py            # pydantic-ai Agent + 7 tools wired to Orqest
│       └── router.py           # /api/workbench/{chat,state,reset,memory/forget}
│
└── frontend/
    ├── next.config.ts          # Rewrites /api/* → localhost:8000
    └── src/
        ├── app/
        │   ├── page.tsx        # Landing (hero + grid of demo cards)
        │   ├── layout.tsx      # dark mode + font wiring
        │   ├── globals.css     # Design tokens (Geist, teal accent)
        │   ├── workbench/      # THE CANONICAL UI
        │   │   └── page.tsx
        │   └── demos/          # Focused demos
        │       ├── chat/page.tsx
        │       ├── artifact/page.tsx
        │       ├── tasks/page.tsx
        │       ├── multimodal/page.tsx
        │       └── research/page.tsx
        └── components/
            ├── demo-shell.tsx  # Sidebar + header wrapper
            ├── ai-elements/    # Vercel AI Elements (vendored)
            └── ui/             # shadcn primitives
```

---

## Extending the Workbench

### Add a new tool

1. Define the async function in `demo/backend/workbench/agent.py`
2. Emit an `AgentEvent` inside it so the Events tab shows activity
3. Register it on the `agent = Agent(tools=[...])` list
4. If it drives a UI panel (like `emit_plan`), add a tab case in
   `demo/frontend/src/app/workbench/page.tsx`

### Add a new right-panel tab

Add to `TAB_ORDER` in the workbench page and write a `*Panel` component.
Each panel receives data from either:
- `useChat` messages (via `useMemo` extracting tool-call parts), or
- The sidecar state (for memory/trace/events that live outside the stream)

### Use a different memory backend

Replace `LocalMemoryStore` in `demo/backend/workbench/state.py`. The
`MemoryStore` protocol is satisfied by any backend (Supabase pgvector is
architected in `orqest.memory` but not yet implemented).

---

## What's deliberately out of scope

- **Multi-session persistence** — memory survives restarts but sessions
  don't (no user auth, no session IDs tied to a user). Add your own.
- **Real web search** — `tools.py::web_search` returns fixture data. Swap in
  Brave/Serper/Exa for production.
- **Human-in-the-loop approvals** — would require AI SDK v6 + `sdk_version=6`
  on the adapter. Currently on v5.
- **Branching conversations** — would require AI Elements `branch` component,
  which is 404 at the registry.

---

## Design principles

1. **Chat is always the anchor.** The right panel swaps context; chat stays
   visible so the user never loses thread.
2. **Show everything by default.** Tool calls, memory writes, plans, and
   artifacts are visible as inline stubs *and* expanded in their panels.
   Silent execution looks like magic but feels like gaslighting.
3. **Structured output, not regex parsing.** Drive UI from typed tool args.
4. **Orqest in the infrastructure, pydantic-ai in the agent.** Don't replace
   what pydantic-ai does well.
5. **Token streaming + hairline progress, never spinners.** A spinner signals
   "something is wrong and I have nothing to tell you." Streaming tokens +
   a progress bar signal "here's what's happening right now."
