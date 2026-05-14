# Autonomy — Runtime Agent Design

Orqest treats agent topology as runtime state, not declared upfront. A planner agent emits an `AgentSpec` as structured output (JSON); the `AgentFactory` hydrates it into a live `DynamicAgent`; the `ToolRegistry` resolves tools by name; the `MetaOrchestrator` decomposes a goal into subtasks and spawns specialists for each. The orchestrator can grow its own organization as it discovers what it needs — and persist named sub-agents across turns so the roster survives.

## What problem does this solve?

LangGraph, CrewAI, AutoGen all require declared topology upfront — you decide which agents exist before any goal arrives. That breaks down for genuinely heterogeneous tasks where the right specialists depend on the work. Autonomy flips the protocol: the LLM proposes the agent (output schema, tools, constraints, model), Orqest hydrates it, and runs it. Combined with cognitive memory typology, the roster persists — next session, "the analyst we trained yesterday" shows up already trained.

## The four primitives

| Primitive | File | Purpose |
|-----------|------|---------|
| `AgentSpec` / `ToolSpec` | `orqest/autonomy/spec.py` | Serializable contracts the LLM emits |
| `AgentFactory` | `orqest/autonomy/factory.py` | Hydrates a spec into a `DynamicAgent` |
| `ToolRegistry` | `orqest/autonomy/registry.py` | Central namespace for tools |
| `MetaOrchestrator` | `orqest/autonomy/meta.py` | Goal → decompose → spawn-or-find → execute |

## AgentSpec & ToolSpec

The serializable contracts. An LLM produces these as structured output via pydantic-ai's typed agent path.

```python
from orqest.autonomy import AgentSpec, ToolSpec

spec = AgentSpec(
    name="rate_limit_analyst",
    system_prompt=(
        "You analyze rate-limit errors. Identify the burst pattern, "
        "propose a backoff strategy, and report confidence."
    ),
    output_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "strategy": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["pattern", "strategy"],
    },
    tools=[
        ToolSpec(name="get_rate_limit_logs", description="Fetch recent 429s"),
        ToolSpec(name="compute_p95_latency", description="Compute p95"),
    ],
    model="openai:gpt-4.1",
    constraints=["Always cite at least one log entry"],
    token_budget=8000,
)
```

| `AgentSpec` field | Type | Meaning |
|-------------------|------|---------|
| `name` | `str` | Unique identifier; used for memory persistence and registry lookup |
| `system_prompt` | `str` | The agent's role/instructions |
| `output_schema` | `dict` | JSON Schema for the structured output (becomes a runtime Pydantic model) |
| `tools` | `list[ToolSpec]` | References to tools by name (resolved via registry) |
| `model` | `str` | `provider:model_id` (defaults to `"openai:gpt-4.1"`) |
| `constraints` | `list[str]` | Free-text constraints injected into the system prompt |
| `token_budget` | `int \| None` | Per-agent token hint (consumer-side enforcement) |
| `metadata` | `dict` | Free-form passthrough |

`ToolSpec.source` is `"registry"` (default — resolve from `ToolRegistry`) or `"dynamic"` (a future hook for sandboxed code generation).

## AgentFactory — hydration

```python
from orqest.autonomy import AgentFactory, ToolRegistry

registry = ToolRegistry()
registry.register(get_rate_limit_logs)   # pydantic_ai.Tool
registry.register(compute_p95_latency)

factory = AgentFactory(
    registry=registry,
    default_model="openai:gpt-4.1",
    api_key="sk-...",
)

agent = factory.spawn(spec)              # returns DynamicAgent
result = await agent.run(state)
```

What `factory.spawn` does:

1. Converts `spec.output_schema` (JSON Schema) → Pydantic model via `pydantic.create_model()`
2. Resolves each `ToolSpec.name` against the registry (skips missing tools with a debug log)
3. Appends `Constraints (you MUST follow these):\n- ...` to the system prompt
4. Constructs a `DynamicAgent[GlobalState, BaseModel]` with the resolved model and tools
5. Returns the runnable agent

For tests, pass `model=TestModel()` directly: `factory.spawn(spec, model=test_model)`.

## ToolRegistry — central namespace

```python
from orqest.autonomy import ToolRegistry
from pydantic_ai import Tool

registry = ToolRegistry()
registry.register(my_tool)               # by tool.name
registry.register(other_tool, description="Override the description")

tool = registry.get("my_tool")           # Tool | None
hits = registry.search("rate limit", k=5)  # keyword scoring
all_names = registry.list_all()
registry.remove("my_tool")
```

### MCP fallback — `get_or_discover`

When a tool name is missing, `get_or_discover` searches MCP for a server that advertises the capability, gates the request through a `PermissionGate` (default `DenyAll`), and registers the discovered tools transparently.

```python
from orqest.mcp import MCPDiscovery, MCPServerManager, AllowList

tool = await registry.get_or_discover(
    "compute_p95_latency",
    discovery=MCPDiscovery(),
    manager=MCPServerManager(),
    permission=AllowList([r"compute\.\.*", r"metrics\..*"]),
    audit_bus=workbench.event_bus,
    max_servers=3,
)
```

Audit events emitted on the bus: `discovery.requested`, `discovery.connected`, `discovery.denied`, `discovery.failed`. See [MCP](mcp.md) for the full picture.

## MetaOrchestrator — runtime decomposition

The orchestrator is the autonomy layer's spine. Goal in, `ExecutionResult` out.

```python
import asyncio
from orqest.autonomy import AgentFactory, MetaOrchestrator, ToolRegistry
from orqest.metacognition import MetacognitionConfig
from orqest.observability import EventBus
from app.agents.planner import PlannerAgent  # outputs TaskDecomposition


async def main():
    registry = ToolRegistry()
    # ... register your tools ...

    factory = AgentFactory(registry=registry, default_model="openai:gpt-4.1", api_key="sk-...")

    bus = EventBus()
    orchestrator = MetaOrchestrator(
        planner=PlannerAgent(...),
        factory=factory,
        registry=registry,
        memory=local_memory_store,        # optional — persists specs across sessions
        max_subtasks=10,
        max_spawn_depth=3,
        metacognition=MetacognitionConfig(redecompose_threshold=0.5),
        bus=bus,
    )

    result = await orchestrator.solve(
        "Investigate the Q3 latency regression and propose a remediation"
    )

    print(f"Success: {result.success}")
    print(f"Summary: {result.summary}")
    for sub in result.subtask_results:
        print(f"  - {sub.subtask_name}: {sub.success} ({sub.duration_ms:.0f}ms)")


asyncio.run(main())
```

What happens:

1. **Decompose** — the planner agent runs with `output_type=TaskDecomposition` and emits a list of `SubTask` records (each carries a `name`, `description`, `requires_agent` flag, optional `agent_name`)
2. **For each subtask**: `_find_or_spawn(subtask)` either retrieves a previously-persisted agent from procedural memory, or has the planner emit an `AgentSpec` and hydrates it via the factory
3. **Execute** the subtask through the spawned agent
4. **Persist** successful specs to memory (dual-write: episodic mirror + procedural `Skill` entry) so future sessions can re-use them
5. **Aggregate** into an `ExecutionResult(goal, success, subtask_results, summary, total_duration_ms)`

| `MetaOrchestrator` ctor arg | Purpose |
|-----------------------------|---------|
| `planner` | `BaseAgent` whose `output_type` is `TaskDecomposition` |
| `factory` | `AgentFactory` (registry-bound) |
| `registry` | `ToolRegistry` |
| `memory` | Optional `MemoryStore` — persists successful agent specs |
| `hooks` | Optional `HookRunner` — Skip/Redirect/Abort honored at the subtask boundary |
| `max_subtasks` | Cap on subtasks per goal (default `10`) |
| `max_spawn_depth` | Cap on nested agent spawning (default `3`) |
| `metacognition` | Optional `MetacognitionConfig` — enables confidence-driven re-decomposition |
| `bus` | Optional `EventBus` — receives `metacognition.redecomposition_triggered` and other autonomy events |

## Confidence-driven re-decomposition

When a `MetacognitionConfig` is supplied, after each successful subtask the orchestrator inspects the result's confidence. If it falls below `redecompose_threshold` (and the re-decomposition budget remains), the planner is re-invoked to rewrite the remaining subtasks.

```python
from orqest.metacognition import MetacognitionConfig

orchestrator = MetaOrchestrator(
    planner=planner,
    factory=factory,
    registry=registry,
    metacognition=MetacognitionConfig(
        redecompose_threshold=0.5,    # below this, re-decompose
        max_redecompositions=2,        # bounded recursion
    ),
    bus=bus,                           # emits metacognition.redecomposition_triggered
)
```

The cross-feature handshake in action: `metacognition` produces the confidence signal; the orchestrator acts on it. Without metacognition, the orchestrator is straight-through.

## Persistent sub-agent roster

When `memory` is configured, `_find_or_spawn` checks procedural memory for a `Skill` entry matching the subtask before asking the planner to emit a fresh `AgentSpec`. Successful runs dual-write back: an episodic mirror entry (legacy compatibility) plus a procedural `Skill` keyed on the subtask trigger.

The result: cross-session continuity. The "rate-limit analyst" you trained yesterday shows up today as soon as the same trigger appears, with its `AgentSpec` already hydrated. See [Memory](memory.md) for the procedural memory shape.

## Hook integration

`MetaOrchestrator._execute_subtask` runs each subtask through the supplied `HookRunner`. Hooks can return:

- `Continue` — proceed normally (default)
- `Skip(stub_result=...)` — skip the subtask, treat the stub as the result
- `Redirect(new_args=..., new_tool=...)` — re-route to a different agent or rewrite arguments
- `Abort(reason=...)` — halt the entire orchestration with `HookAbortError`

This is the same `HookDecision` plumbing used by self-healing's `WatchdogHook`. A regression detector that sees confidence drop mid-orchestration can `Redirect` to a different model or `Abort` cleanly.

## Best practices

- **Pass `model=TestModel()` to `factory.spawn` in tests.** Don't rely on the real LLM resolution path; the factory accepts an explicit model override for this reason.
- **Constrain via the spec, not by editing the system prompt.** `AgentSpec.constraints` are appended in a separate block (`Constraints (you MUST follow these):`) so they survive prompt iteration.
- **Use `max_spawn_depth` defensively.** A planner that spawns sub-planners that spawn sub-sub-planners blows up cost without the depth cap.
- **Wire metacognition + memory together.** Confidence-driven re-decomposition + procedural persistence is the substrate's flagship loop; both are opt-in but compose cleanly.
- **Polymath uses every part.** See `~/repos/orqest/demo/polymath/` for an end-to-end deployment of the autonomy layer with a persistent sub-agent roster, healing, generative UI, and a frontend that visualizes the roster.

## Pitfalls

- **Don't share a `MetaOrchestrator` across requests.** It owns `_spawned_agents` for the run; reuse leaks state across users.
- **Don't bypass `ToolRegistry` to inject tools directly into `factory.spawn`.** The registry is the audit trail and the discovery surface; ad-hoc injection breaks `get_or_discover` and the per-tool MCP audit events.
- **Don't trust `output_schema` from an untrusted source.** `pydantic.create_model()` runs at spawn time; a malicious schema can blow up your process. If consumer-supplied specs are in scope, validate before spawning.
- **Don't read `_spawned_agents` from outside the orchestrator.** It's an implementation detail; access patterns may change. Use `MemoryStore.recall` with `memory_type="procedural"` for the authoritative roster.

## What's happening under the hood

1. `solve(goal)` calls `_decompose(goal)` → planner agent with `output_type=TaskDecomposition`
2. For each `SubTask`: `_find_or_spawn(subtask)` checks procedural memory; if found, hydrates from the persisted `AgentSpec`; otherwise asks the planner to emit a fresh spec
3. `factory.spawn(spec)` constructs a `DynamicAgent`:
   - JSON Schema → Pydantic model via `create_model()`
   - Tool names resolved against `ToolRegistry`
   - Constraints injected into the system prompt
4. `_execute_subtask(subtask)` runs the agent through the `HookRunner`; `HookDecision` honored at the boundary
5. On success, dual-write to memory (episodic + procedural)
6. Confidence checked: re-decompose remaining subtasks if `metacognition` configured and confidence < threshold
7. Aggregate to `ExecutionResult`

## Related Concepts

- [Memory](memory.md) — procedural `Skill` entries that persist sub-agents across sessions
- [Metacognition](metacognition.md) — `EnrichedOutput.confidence` drives `redecompose_threshold`
- [Self-Healing](healing.md) — `WatchdogHook` returns `HookDecision`s that flow through the same orchestrator boundary
- [MCP](mcp.md) — `ToolRegistry.get_or_discover` for missing-capability discovery
- [Hooks & Lifecycle](hooks-and-lifecycle.md) — `HookDecision` semantics
