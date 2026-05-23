# Autonomy — reference

Compressed judgment layer over `orqest/autonomy/`. For full reference + edge cases, read `docs/concepts/autonomy.md`.

## What this layer solves

Most agentic frameworks (LangGraph, CrewAI, AutoGen) declare topology upfront — you decide which agents exist before any goal arrives. That breaks down for heterogeneous tasks. The autonomy layer flips the protocol: an LLM proposes the agent (`AgentSpec`), Orqest hydrates and runs it (`AgentFactory`), and the orchestrator (`MetaOrchestrator`) decomposes a goal into subtasks that spawn the specialists they need. Combined with procedural memory, the roster persists across sessions.

**When NOT to reach for this:** if you know the decomposition at build time, hand-write a `Pipeline`. The planner LLM call inside `MetaOrchestrator` is typically the most expensive single invocation per request; pay it only when the decomposition itself is the hard part.

## The four primitives

| Primitive | Purpose |
|---|---|
| `AgentSpec` / `ToolSpec` | Serializable contracts an LLM emits as structured output |
| `AgentFactory` | Hydrates a spec into a `DynamicAgent` |
| `ToolRegistry` | Central namespace; resolves tool names → `pydantic_ai.Tool` |
| `MetaOrchestrator` | Goal → decompose → spawn-or-find → execute → aggregate |

Plus two newer primitives for runtime tool authoring:

| Primitive | Purpose |
|---|---|
| `GeneratedToolSpec` | Serializable contract carrying a Python `implementation` string |
| `DynamicToolFactory` | Validates + executes `GeneratedToolSpec` via a `Sandbox` |

## `AgentSpec` — minimal wire-up

```python
from orqest.autonomy import AgentSpec, ToolSpec

# JSON Schema path — for LLM-emitted or persisted specs (serialises cleanly)
spec = AgentSpec(
    name="rate_limit_analyst",
    system_prompt="You analyze rate-limit errors. Identify the burst pattern, propose backoff, report confidence.",
    output_schema={
        "type": "object",
        "properties": {
            "pattern":    {"type": "string"},
            "strategy":   {"type": "string"},
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

# Pydantic-class path — terser for code-side specs; not serialisable
from pydantic import BaseModel
class AnalystOut(BaseModel):
    pattern: str
    strategy: str
    confidence: float

spec = AgentSpec(
    name="rate_limit_analyst",
    system_prompt="...",
    output_type=AnalystOut,                     # exactly-one-of with output_schema
)
```

**Exactly-one-of.** Setting both `output_schema` and `output_type` raises; setting neither raises. Use `output_schema` when the spec crosses a serialisation boundary (LLM-emitted, persisted, transmitted). Use `output_type` for in-process construction.

## `AgentFactory` — hydration

```python
from orqest.autonomy import AgentFactory, ToolRegistry

registry = ToolRegistry()
registry.register(get_rate_limit_logs)          # by tool.name
registry.register(compute_p95_latency)

factory = AgentFactory(registry=registry, default_model="openai:gpt-4.1", api_key="sk-...")
agent = factory.spawn(spec)                     # → DynamicAgent[GlobalState, BaseModel]
result = await agent.run(state)
```

What `spawn` does: JSON Schema → Pydantic model via `pydantic.create_model()`; tool names resolved against registry (missing names dropped with debug log); constraints appended in a separate `Constraints (you MUST follow these):` block; agent constructed.

For tests: `factory.spawn(spec, model=TestModel())`. Every constructor accepts an explicit model override.

## `ToolRegistry` — central namespace

```python
from orqest.autonomy import ToolRegistry

registry = ToolRegistry()
registry.register(my_tool)
registry.register(other_tool, description="Override description")
tool = registry.get("my_tool")                  # → Tool | None
hits = registry.search("rate limit", k=5)       # keyword scoring
all_names = registry.list_all()
registry.remove("my_tool")
```

### MCP fallback — `get_or_discover`

When a tool name is missing, `get_or_discover` searches MCP, gates the request through a `PermissionGate` (default `DenyAll`), and registers discovered tools transparently:

```python
from orqest.mcp import MCPDiscovery, MCPServerManager, AllowList

tool = await registry.get_or_discover(
    "compute_p95_latency",
    discovery=MCPDiscovery(),
    manager=MCPServerManager(),
    permission=AllowList([r"compute\..*", r"metrics\..*"]),
    audit_bus=wb.event_bus,
    max_servers=3,
)
```

Bus events: `discovery.requested`, `discovery.connected`, `discovery.denied`, `discovery.failed`.

## `MetaOrchestrator` — goal-driven decomposition

```python
from orqest.autonomy import MetaOrchestrator
from orqest.metacognition import MetacognitionConfig

orchestrator = MetaOrchestrator(
    planner=planner_agent,                      # outputs TaskDecomposition
    factory=factory,
    registry=registry,
    memory=wb.memory,                           # optional — persists specs as procedural Skills
    bus=wb.event_bus,                           # optional — receives metacognition.redecomposition_triggered etc.
    hooks=hook_runner,                          # optional — Skip/Redirect/Abort honored at subtask boundary
    metacognition=MetacognitionConfig(redecompose_threshold=0.5, max_redecompositions=2),
    max_subtasks=10,
    max_spawn_depth=3,
)
result = await orchestrator.solve("Investigate the Q3 latency regression and propose a remediation")
```

Flow: `_decompose(goal)` → planner with `output_type=TaskDecomposition` → per `SubTask`, `_find_or_spawn` checks procedural memory then asks planner to emit a fresh `AgentSpec` → `factory.spawn` → execute through `HookRunner` → dual-write (episodic mirror + procedural `Skill`) → aggregate to `ExecutionResult`.

### Confidence-driven re-decomposition

After each successful subtask, if `metacognition` is configured and the result's confidence falls below `redecompose_threshold` (and budget remains), the planner is re-invoked to rewrite the remaining subtasks. The cross-feature handshake: metacognition produces the signal; the orchestrator acts on it.

## Dynamic tool spawning — `GeneratedToolSpec` + `DynamicToolFactory`

When the LLM needs a capability no registered tool provides, it can emit a `GeneratedToolSpec` carrying the Python implementation:

```python
from orqest.autonomy import GeneratedToolSpec, DynamicToolFactory, AgentFactory
from orqest.sandbox import SubprocessSandbox

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
    dependencies=[],                            # pip specifiers (Tier-2 DockerSandbox only)
    timeout_s=2.0,
    memory_mb=64,
)

tool_factory = DynamicToolFactory(SubprocessSandbox())
doi_tool = await tool_factory.spawn(extract_dois)   # → pydantic_ai.Tool

# Wire into AgentFactory so AgentSpec.tools can mix registered + generated
agent_factory = AgentFactory(registry=registry, tool_factory=tool_factory)
spec = AgentSpec(
    name="researcher", system_prompt="...", output_schema={...},
    tools=[ToolSpec(name="search"), extract_dois],   # smart-union dispatch
)
```

The body receives a single `args` dict (matching `parameters`) and `return`s a JSON-serializable value. `allowed_imports` is the safety surface — empty (default) rejects any `import` at validate time. `dependencies` is only honored by Tier-2 `DockerSandbox` (Tier-0/1 ignore — no per-agent venv).

On failure the tool returns a structured error dict, not a Python exception, so the agent loop sees it as a tool result.

## Runtime tool assignment — `BaseAgent.add_tool`

```python
agent.add_tool(doi_tool)        # appends + invalidates _agent cache
```

Next access to `agent.agent` rebuilds the pydantic-ai Agent with the new tool list. Idempotent for same-name tools (last-write-wins). **In-flight `agent.run()` calls don't see new tools** — they captured the list at start.

## Pitfalls

- **Don't share a `MetaOrchestrator` across requests.** It owns `_spawned_agents` for the run; reuse leaks state across users.
- **Don't bypass `ToolRegistry` to inject tools directly.** The registry is the audit trail and the MCP discovery surface; ad-hoc injection breaks `get_or_discover` and audit events.
- **Don't trust `output_schema` from an untrusted source.** `pydantic.create_model()` runs at spawn time; a malicious schema can blow up the process.
- **`max_spawn_depth` is defensive.** A planner that spawns sub-planners that spawn sub-sub-planners explodes cost. Default `3`. Don't raise it without budget controls.
- **`tool_factory=None` skips `GeneratedToolSpec`s with a warning.** Same graceful-degradation pattern as unknown registry names. If you want hard failure, validate specs upstream.

## Best practices

- Pass `model=TestModel()` to `factory.spawn` in tests. The factory accepts it for this reason.
- Constrain via `AgentSpec.constraints`, not by editing the system prompt — constraints survive prompt iteration in a separate block.
- Wire `metacognition + memory + bus` together. Confidence-driven re-decomposition + procedural persistence is the substrate's flagship loop.

## Where to read more

- `docs/concepts/autonomy.md` — full reference (incl. dynamic tool spawning, per-user persistence, future seams)
- `docs/concepts/memory.md` — procedural `Skill` shape for the persistent roster
- `docs/concepts/sandbox.md` — `Sandbox` Protocol; Tier-0/1/2 backends; `DockerSandbox` per-user MCP tool library
- `docs/concepts/metacognition.md` — `EnrichedOutput.confidence` drives `redecompose_threshold`
- `docs/concepts/mcp.md` — `get_or_discover`, `PermissionGate`, `MCPDiscovery`
- `notebooks/02_meta_orchestrator.ipynb` — runnable end-to-end demo
- `notebooks/10_runtime_topology.ipynb` — `RuntimeTopologyDesigner` adaptive topologies
- `notebooks/11_dynamic_tools.ipynb` — `GeneratedToolSpec` end-to-end
