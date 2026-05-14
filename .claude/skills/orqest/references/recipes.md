# Pattern Recipes

Eight named patterns. Each lists the **assumptions** (Phase A answers it requires), **integration points** (what it touches in the existing codebase), **working code**, **variations**, and **skip if** conditions.

> **Use the lookup table first** to pick a recipe, then read the recipe.

## Lookup table — application shape → minimal surface

| Application shape | Minimal Orqest surface | Recipe | Skip these |
|-------------------|-----------------------|--------|-----------|
| User asks a question, agent uses 1-2 tools, returns text | `BaseAgent` only | **R1** | Workbench, memory, healing, MetaOrchestrator |
| Same as above + frontend wants tool-call visibility | `BaseAgent` + `Workbench` + `EventBus` + `sse_sidecar` | **R1+** | memory, healing, MetaOrchestrator |
| Multi-step research with intermediate artifacts | `Pipeline` + `BaseAgent` per step | **R2** | memory unless cross-session |
| Independent sub-tasks fan-out + merge | `Parallel` + `BaseAgent` × N | **R3** | memory unless cross-session |
| Self-improving output ("draft → critique → refine") | `RefinementLoop` (with `confidence_threshold` if metacognition genuinely adds value) | **R4** | memory unless cross-session; MetaOrchestrator |
| Cross-session continuity (user expects "remember last time") | + `LocalMemoryStore` | **R5** | depends on rest |
| Dynamic decomposition into specialists | `MetaOrchestrator` + `AgentFactory` + `ToolRegistry` | **R6** | only when task is genuinely heterogeneous |
| Production with rate-limit / outage resilience | + `Workbench.with_healing(...)` | **R7** | only when in production traffic |
| Agent renders charts/tables/forms in a frontend that supports SSE | + `UIEmitter` + `UIComponentSpec` subclasses | **R8** | only when frontend already does SSE |

---

## R1 — Conversational agent with tools

**Assumes:** simple Q&A; existing app provides tool functions; no cross-session memory needed; user-triggered request/response.

**Integration points:** the agent module imports the existing app's read functions; the route handler instantiates the agent per-request and returns its output.

```python
# app/agents/orders_summary.py
from pydantic import BaseModel, Field
from orqest.agents import BaseAgent, GlobalState
from app.orders.queries import get_recent_orders  # existing app function


class OrderSummary(BaseModel):
    total_count: int
    summary: str = Field(description="Markdown overview")


class OrdersAgent(BaseAgent[GlobalState, OrderSummary]):
    """Summarizes a user's recent orders."""


async def get_recent_orders_tool(user_id: str, limit: int = 10) -> list[dict]:
    """Return the user's most recent orders. ``limit`` defaults to 10."""
    return await get_recent_orders(user_id=user_id, limit=limit)


def build(*, user_id: str, model: str, api_key: str) -> OrdersAgent:
    return OrdersAgent(
        agent_name="orders_summary",
        system_prompt=(
            f"Summarize orders for user {user_id} as Markdown. "
            "Call get_recent_orders to fetch them."
        ),
        output_type=OrderSummary,
        model=model,
        api_key=api_key,
        tools=[get_recent_orders_tool],
    )
```

**Variations:**
- Multiple tools: pass a list to `tools=[...]`
- Stream tokens: use `agent.call_model_stream(...)` instead of `run()`
- Wrap a sub-agent as a tool: `as_tool(other_agent)` from `orqest.agents`

**Skip this recipe if** the agent needs to spawn specialists (use R6) or the topology varies per goal.

---

## R1+ — R1 with tool-call visibility on the frontend

Add a `Workbench` for the event bus. The frontend subscribes to `tool.before / .after / .error` via `sse_sidecar`.

```python
from orqest import Workbench
from orqest.observability import EventBus, EventBusPublishHook
from orqest.hooks import HookRunner

bus = EventBus()
workbench = Workbench(memory=None, event_bus=bus)
hook_runner = HookRunner(hooks=[EventBusPublishHook(bus)])

agent = OrdersAgent(
    agent_name="orders_summary",
    system_prompt="...",
    output_type=OrderSummary,
    model=...,
    api_key=...,
    tools=[get_recent_orders_tool],
    hook_runner=hook_runner,  # tool events fire on the bus
)
```

Mount `sse_sidecar(bus, replay=list(workbench.recent_events), heartbeat_s=15.0)` on a route the frontend subscribes to. See `references/ai_sdk_integration.md` for the React side.

---

## R2 — Sequential research pipeline

**Assumes:** multi-step task with intermediate artifacts; failures should retry per-step; no fan-out needed.

```python
from orqest import Pipeline
from orqest.orchestration import StepConfig
from orqest.orchestration.types import ErrorStrategy

pipeline = Pipeline(
    name="research_to_draft",
    steps=[
        (ResearchAgent(...), StepConfig(name="research", on_error=ErrorStrategy.RETRY, max_retries=2)),
        (SynthesizeAgent(...), StepConfig(name="synthesize", on_error=ErrorStrategy.STOP)),
        (DraftAgent(...), StepConfig(name="draft", on_error=ErrorStrategy.STOP)),
    ],
)

result = await pipeline.run(initial_input)
```

**Variations:**
- Skip-on-error: `ErrorStrategy.SKIP`
- Pure async function in the middle: pass a callable, it gets auto-coerced via `_coerce_step`
- Refinement on the final step: wrap `DraftAgent` in `RefinementLoop(confidence_threshold=0.85)`

**Skip this recipe if** the steps are independent (use R3) or topology is dynamic (use R6).

---

## R3 — Parallel fan-out + merge

**Assumes:** independent sub-tasks; latency matters more than cost; outputs combine deterministically.

```python
from orqest import Parallel
from orqest.orchestration.parallel import MergeStrategy

parallel = Parallel(
    name="multi_provider_search",
    steps=[ProviderA(...), ProviderB(...), ProviderC(...)],
    merge=MergeStrategy.collect_all,
    timeout_s=10.0,
)

results = await parallel.run(query)  # ParallelResult.merged is list of all outputs
```

**Variations:**
- First-wins racing: `merge=MergeStrategy.first_wins`
- Custom merger: `merge=lambda outputs: combined_output(outputs)`

**Skip this recipe if** branches depend on each other (use R2).

---

## R4 — Confidence-gated refinement loop

**Assumes:** quality matters; agent has a notion of "good enough"; willing to spend extra LLM calls; output type carries `self_confidence` (or use `LLMSelfRatingProtocol`).

```python
from orqest import RefinementLoop
from orqest.metacognition import StructuredOutputProtocol

writer = WriterAgent(
    ...,
    confidence_protocol=StructuredOutputProtocol(),  # output has self_confidence field
)

loop = RefinementLoop(
    step=writer,
    evaluator=CriticAgent(...),         # rates output as EvalResult
    state_updater=update_with_feedback,
    max_iterations=5,
    confidence_threshold=0.85,           # exit early when confident
)

result = await loop.run(state)
print(result.exit_reason)  # "passed" | "confident" | "max_iterations" | "converged"
```

**Variations:**
- Self-eval (no separate critic): `RefinementLoop(step=writer, agent_self_eval=writer, confidence_threshold=0.85, evaluator=_unused, state_updater=...)` — see `examples/05_refinement_loop/main.py`
- Convergence detection: `convergence_window=2` to exit when output stops changing

**Skip this recipe if** there's no notion of "better" — pure single-shot tasks just use a `BaseAgent`.

---

## R5 — Memory-backed long-running agent

**Assumes:** cross-session continuity; existing app has a session-id concept; willing to store agent state in Orqest's SQLite (or wire a custom backend via `MemoryStore` Protocol).

```python
from orqest.memory import LocalMemoryStore, MemoryEntry, MemoryFilter, Skill, ToolCallSpec
from orqest.workbench import Workbench

memory = LocalMemoryStore("/var/app/memory.db")
workbench = Workbench(memory=memory)

# Store a fact (semantic)
await memory.store(MemoryEntry(
    content="User prefers concise responses, no preamble.",
    memory_type="semantic",
    source_agent="orders",
    confidence=0.9,
    metadata={"session_id": session_id, "user_id": user_id},
))

# Recall facts for this user
facts = await memory.recall(
    "user preferences",
    k=5,
    filters=MemoryFilter(memory_type="semantic"),
)
relevant = [f for f in facts if f.metadata.get("user_id") == user_id]

# Store a procedural skill (a learned tool sequence)
await memory.store(MemoryEntry(
    content="how to reconcile orders with refunds",
    memory_type="procedural",
    structured_content=Skill(
        name="reconcile_orders",
        version=1,
        trigger="reconcile",
        steps=[ToolCallSpec(tool="get_recent_orders", args_schema={"limit": 50})],
        examples=[],
    ).model_dump(),
))
```

**Integration points:** the existing app provides `session_id` and `user_id`; the agent wraps `memory.recall(...)` calls in tools that pass these as filters. Memory is best-effort — `LocalMemoryStore` swallows SQLite errors and logs.

**Variations:**
- Custom backend: implement `MemoryStore` Protocol; pass to `Workbench(memory=...)`
- Per-kind reliability policy (decay-on-failure, prune floor): `MemoryConfig` with a `PerKindConfig` per kind, passed as `LocalMemoryStore(config=...)`

**Skip this recipe if** the app already has its own context store — extend that instead of bolting on memory.

---

## R6 — Multi-agent orchestration (runtime agent design)

**Assumes:** task is genuinely heterogeneous (different specialists for different sub-goals); sub-agents should persist across turns; planner knows how to decompose; willing to let the LLM emit `AgentSpec` JSON.

```python
from orqest.autonomy import AgentSpec, AgentFactory, MetaOrchestrator, ToolRegistry
from orqest.metacognition import MetacognitionConfig
from orqest.workbench import Workbench
from app.agents.planner import PlannerAgent  # outputs TaskDecomposition

registry = ToolRegistry()
registry.register(some_tool)
registry.register(another_tool)

factory = AgentFactory(
    registry=registry,
    default_model="openai:gpt-4.1",
    api_key="sk-...",
)

orchestrator = MetaOrchestrator(
    planner=PlannerAgent(...),
    factory=factory,
    registry=registry,
    memory=local_memory_store,           # optional — persists agent specs across sessions
    metacognition=MetacognitionConfig(redecompose_threshold=0.5),
    bus=workbench.event_bus,
)

result = await orchestrator.solve(goal="Investigate Q3 revenue dip and propose causes")
```

**Variations:**
- Persistent sub-agent roster: built-in (dual-write episodic + procedural memory entries via `_find_or_spawn`)
- Custom decomposition: subclass `MetaOrchestrator._decompose`

**Skip this recipe if** the task fits a static pipeline. Dynamic decomposition is overhead; only worth it when the task shape varies per goal.

---

## R7 — Production-ready agent (healing + fallback)

**Assumes:** agent runs in production traffic; rate limits / outages are real; user can tolerate model swap mid-task.

```python
from orqest.healing import HealingConfig
from orqest.workbench import Workbench
from orqest.observability import EventBus

bus = EventBus()
workbench = Workbench(memory=memory, event_bus=bus)

healing = workbench.with_healing(
    HealingConfig(
        stall_timeout_s=30.0,
        loop_threshold_k=3,
        loop_window_n=10,
        regression_window_n=10,
        regression_drop_threshold=0.2,
        poll_interval_s=1.0,
        fallback_models=("openai:gpt-4.1", "anthropic:claude-sonnet-4-6"),
    ),
    api_key={"openai": "sk-...", "anthropic": "sk-ant-..."},
)

async def handle_request(payload):
    async with healing as runner:
        agent = MyAgent(
            ...,
            model=runner.model,             # FallbackModel
            hook_runner=runner.hook_runner,  # WatchdogHook + EventBusPublishHook
        )
        return await agent.run(state)
```

**Variations:**
- Custom recovery policy: pass `policy=my_policy` to `WatchdogHook`
- Wire the bus to existing observability: subscribe handlers that forward to your tracer

**Skip this recipe if** the agent runs offline / batch / dev only — healing's overhead doesn't pay off.

---

## R8 — Generative UI emission

**Assumes:** existing frontend can subscribe to SSE and render typed components; you control both ends; the agent's output benefits from a richer surface than text.

```python
from orqest.observability import EventBus, sse_sidecar
from orqest.ui import (
    ChartComponent,
    ChartComponentData,
    ChartSeries,
    UIEmitter,
)

bus = EventBus()
emitter = UIEmitter(bus)

# Inside an agent or a tool:
chart = ChartComponent(
    component_id="latency-chart",
    data=ChartComponentData(
        kind="line",
        title="Request latency",
        series=[ChartSeries(name="p50", points=[{"x": 0, "y": 12}])],
    ),
)
emitter.init(chart)

# In a FastAPI route:
@app.get("/sessions/{session_id}/events")
async def events(session_id: str):
    bus = get_bus_for(session_id)
    return EventSourceResponse(sse_sidecar(bus, replay=(), heartbeat_s=15.0))
```

**Frontend** subscribes to `ui.chart.init` / `ui.chart.delta` / `ui.chart.remove` events and resolves a renderer keyed on `component_type`. See `references/ai_sdk_integration.md` for the full Polymath-style React integration.

**Variations:**
- Custom component: subclass `UIComponentSpec[T]`, register with `ComponentRegistry`
- Patch deltas: `emitter.delta("latency-chart", op="append", path="series.0.points", value={"x":1,"y":14})`
- Layer 2 grammars: `VegaChartComponent`, `MermaidComponent`, `LatexComponent`, `JsonViewerComponent`
- Layer 3 escape hatch: `SandboxedHTMLComponent` for one-offs

**Skip this recipe if** the existing frontend doesn't speak SSE. Don't bolt SSE on for the sake of one agent — return structured data instead.
