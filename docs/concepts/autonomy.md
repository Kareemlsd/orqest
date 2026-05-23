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

`ToolSpec.name` is resolved against the `ToolRegistry` at spawn time. Specs whose name doesn't resolve are silently dropped (the agent still spawns with whatever does resolve) — register the missing tool first or wire `ToolRegistry.get_or_discover` for MCP fallback.

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

## When NOT to use `MetaOrchestrator` — just write the agents and a Pipeline

`MetaOrchestrator` adds a planner LLM call per request — typically the most expensive single agent invocation in the chain. That cost is only worth paying when **you don't know the task decomposition in advance**. If you DO know it (most production workloads do), the simpler answer is to instantiate the agents you need and compose them with `Pipeline` / `Parallel` / `Router` directly:

```python
# When the decomposition is stable: hand-written pipeline beats meta-orchestration.
pipeline = Pipeline([
    researcher_agent,
    summariser_agent,
    fact_checker_agent,
])
result = await pipeline.run(user_query)
```

Three honest tests for "should I reach for this primitive":

| Test | Hand-write a Pipeline | Use `MetaOrchestrator` |
|---|---|---|
| **Decomposition stability:** does the same input shape always need the same subtasks? | Yes — known stages | No — every goal decomposes differently |
| **Specialist roster:** is the set of specialists known at build time? | Yes — finite, listable | No — emergent per-goal |
| **Cost budget:** can you afford an extra planner LLM call (typically the most expensive in the chain) per request? | Saves the planner call | Worth paying for the routing |

The MetaOrchestrator's value shows up sharply when the decomposition is *itself* the hard part — open-ended research, multi-domain triage, anything where "what subtasks does this break into?" needs an LLM to answer. For a CSV-to-JSON converter or a known QA pipeline, you don't need it. Reach for the simpler primitive when it fits.

(Same principle for `RuntimeTopologyDesigner` — see [Topology Optimization → When NOT to use](topology_optimization.md#when-not-to-use-runtimetopologydesigner--just-hand-write-a-pipeline).)

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

## Dynamic tool spawning

`AgentSpec.tools` was historically a wishlist — `AgentFactory._resolve_tools` looked up each `ToolSpec` in `ToolRegistry` and silently dropped the unknowns. So when an LLM emitted an `AgentSpec` requesting a brand-new capability, the agent spawned without it. **`GeneratedToolSpec` + `DynamicToolFactory` close that gap.**

### `GeneratedToolSpec` — implementation included

```python
from orqest.autonomy import GeneratedToolSpec

extract_dois = GeneratedToolSpec(
    name="extract_dois",
    description="Extract DOIs from a text blob.",
    parameters={"text": {"type": "string"}},
    implementation=(
        "import re\n"
        "matches = re.findall(r'10\\.\\d{4,}/[\\w.\\-/]+', args['text'])\n"
        "return {'dois': matches, 'count': len(matches)}\n"
    ),
    allowed_imports={"re"},
    dependencies=[],     # pip specifiers; gated by the sandbox's allowed_packages allowlist
    timeout_s=2.0,
    memory_mb=64,
)
```

The body receives a single `args` dict (matching `parameters`) and `return`s a JSON-serializable value. `allowed_imports` is the safety surface — empty (the default) rejects any `import` statement at validate time. `dependencies` declares pip-installable packages the implementation needs (only honored by Tier-2 [`DockerSandbox`](sandbox.md#dockersandbox-tier-2); Tier-0/1 ignore — they don't have a per-agent venv). `timeout_s` and `memory_mb` cap each invocation.

### `DynamicToolFactory` — spec to runnable Tool

```python
from orqest.autonomy import DynamicToolFactory
from orqest.sandbox import SubprocessSandbox

tool_factory = DynamicToolFactory(SubprocessSandbox())
doi_tool = await tool_factory.spawn(extract_dois)   # pydantic_ai.Tool
```

`spawn()` validates the implementation through the configured [Sandbox](sandbox.md) (raising `ValidationError` on failure), then returns a `pydantic_ai.Tool` whose body delegates to `sandbox.execute()` at invocation time. On failure, the tool returns a structured error dict (not a Python exception) so the agent loop sees it as a tool result.

### `AgentFactory(tool_factory=...)` — mixed registered + generated

`AgentSpec.tools` accepts a mixed list. Pydantic v2 smart-union dispatches by structure (the `implementation` field on `GeneratedToolSpec` is the disambiguator):

```python
from orqest.autonomy import AgentFactory, AgentSpec, ToolSpec

agent_factory = AgentFactory(registry=tool_registry, tool_factory=tool_factory)
spec = AgentSpec(
    name="researcher",
    system_prompt="...",
    output_schema={...},
    tools=[
        ToolSpec(name="search", description="..."),         # registered → registry lookup
        extract_dois,                                       # generated  → tool_factory.spawn
    ],
)
agent = agent_factory.spawn(spec)   # both tools resolve + bind
```

When `tool_factory is None` and a `GeneratedToolSpec` appears, the factory logs a warning and skips it (matches the existing graceful-degradation behavior for unknown registry names).

### `BaseAgent.add_tool` — runtime tool assignment

For agents already constructed, hand them tools at runtime:

```python
agent.add_tool(doi_tool)        # appends + invalidates _agent cache
```

The next access to `agent.agent` (the underlying lazily-constructed `pydantic_ai.Agent`) rebuilds with the new tool list. Idempotent for tools sharing a `name` (last-write-wins). **In-flight `Agent.run()` calls don't see the new tool** — the rebuild happens on next access; in-flight runs use the tool list captured at start.

This pattern closes the autonomy ladder's missing rung: an agent that encounters a capability gap mid-run can be handed the missing tool by the orchestrator, without rebuilding the agent from scratch.

### Per-user persistence with `Workbench(user_id, session_id)` + `with_docker_sandbox`

For runtime-spawned tools that should outlive a single session, route the factory through the Tier-2 [DockerSandbox](sandbox.md#dockersandbox-tier-2). The container's per-user MCP tool library auto-promotes any `(name, code_hash)` pair that succeeds N=3 times (default), persists it to a per-user named volume, and replays it on the user's next session — all without the LLM re-asking for it.

```python
from uuid import uuid4
from orqest import Workbench
from orqest.autonomy import AgentFactory, DynamicToolFactory

wb = Workbench(user_id="alice", session_id=str(uuid4()))   # required args
async with wb.with_docker_sandbox(
    image="orqest/agent-runtime:0.8.0",
    allowed_packages={"pandas", "re"},
) as sandbox:
    tool_factory = DynamicToolFactory(sandbox)
    agent_factory = AgentFactory(registry=tool_registry, tool_factory=tool_factory)
    # The LLM-emitted spec can now declare dependencies — the container's
    # executor uv-pip-installs them into the agent's per-agent venv if they
    # appear in `allowed_packages`. Otherwise the call rejects with a
    # `dependency.rejected` bus event.
    agent = agent_factory.spawn(spec)
```

`user_id` becomes the strict isolation key for the persisted library — alice's tools live in volume `orqest-user-alice`; bob never sees them.

### Future seams

- **W3.J — Procedural-memory persistence (host-side mirror).** Phase 13 ships per-user *container-side* tool persistence; the host-side `LocalMemoryStore` mirror with `memory_type="tool"` is the in-progress complement for orqest-side discoverability + observability.
- **W3.C — ADAS sandboxed codegen.** `MetaAgentSearch` extended so the meta agent can emit raw Python `forward()` for cases compositions of registered primitives can't express. Now unblocked by the sandbox.
- **Tier 3 — `MicroVMSandbox`.** Firecracker/Kata/gVisor for adversarial multi-tenant workloads.

## Declaring output shape: `output_schema` vs `output_type`

`AgentSpec` accepts the output declaration via **exactly one** of two fields:

| Field | Type | When to use |
|---|---|---|
| `output_schema` | `dict[str, Any]` (JSON Schema) | **Wire-format option.** When the spec is emitted by an LLM (e.g., by a planner agent inside `MetaOrchestrator`), persisted to disk, or transmitted across a process boundary. JSON Schema serialises cleanly. |
| `output_type` | `type[BaseModel]` (Pydantic class) | **Code-side option.** When you're constructing the spec in Python. Terser than authoring JSON Schema by hand, gets static typing on the output. Not serialisable — don't use this path for LLM-emitted specs. |

```python
from pydantic import BaseModel
from orqest.autonomy import AgentSpec, AgentFactory

# Pydantic-class path (typical for in-process specs)
class CoderOutput(BaseModel):
    reasoning: str
    code: str

spec = AgentSpec(
    name="coder",
    system_prompt="Write code.",
    output_type=CoderOutput,   # ← single field
)

# JSON Schema path (typical for LLM-emitted specs)
spec = AgentSpec(
    name="coder",
    system_prompt="Write code.",
    output_schema={
        "properties": {
            "reasoning": {"type": "string"},
            "code": {"type": "string"},
        },
        "required": ["reasoning", "code"],
    },
)

agent = AgentFactory().spawn(spec, model=...)
```

A `@model_validator` enforces exactly-one-of: setting both fields raises (so the two declarations can't drift), and setting neither raises (no implicit shape inference).

## Related Concepts

- [Memory](memory.md) — procedural `Skill` entries that persist sub-agents across sessions
- [Sandbox](sandbox.md) — safe execution surface for `GeneratedToolSpec` implementations
- [Metacognition](metacognition.md) — `EnrichedOutput.confidence` drives `redecompose_threshold`
- [Self-Healing](healing.md) — `WatchdogHook` returns `HookDecision`s that flow through the same orchestrator boundary
- [MCP](mcp.md) — `ToolRegistry.get_or_discover` for missing-capability discovery
- [Hooks & Lifecycle](hooks-and-lifecycle.md) — `HookDecision` semantics

## Runnable demo

[`notebooks/02_meta_orchestrator.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/02_meta_orchestrator.ipynb) — decompose a goal, spawn specialists at runtime, persist the roster.
