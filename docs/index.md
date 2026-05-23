# Orqest

Typed agent primitives and orchestration on top of [pydantic-ai](https://ai.pydantic.dev) — memory, autonomy, self-healing, metacognition, generative UI, MCP, and reflective optimization. All opt-in.

Orqest is not a framework with its own runtime, server, or UI. It is a Python library you import to build one. Each capability is a composable battery that can be picked up à-la-carte. The agent loop remains under your control.

## Install

Requires Python 3.12 or later.

=== "pip"

    ```bash
    pip install orqest
    ```

=== "uv"

    ```bash
    uv add orqest
    ```

Set `LLM_MODEL` and `LLM_API_KEY` to point at a provider, or pass them explicitly to each agent constructor. The provider prefix selects the SDK; see [Getting Started](getting-started.md) for the full table.

```bash
LLM_API_KEY=your_key_here
LLM_MODEL=openai:gpt-4.1
```

## What Orqest provides

The library is organised into batteries. Each one is independently useful and can be adopted without taking on the others.

### Agents that report their own confidence

Every agent can return a confidence score, a list of what it was uncertain about, and a flag for whether the task is outside its capability. The mechanism is pluggable: three protocols are shipped — one that costs no extra calls, one that adds a single self-rating call, and one that runs `k` calls in parallel and computes agreement.

```python
from orqest.metacognition import StructuredOutputProtocol

enriched = await agent.run_enriched(state, confidence_protocol=StructuredOutputProtocol())
print(enriched.confidence, enriched.uncertainty_targets, enriched.capability_boundary)
```

The signal is reused elsewhere. `RefinementLoop(confidence_threshold=0.85)` exits as soon as the agent reports a confident result. `MetaOrchestrator` re-decomposes a plan when subtask confidence falls below a configured threshold. See [Metacognition](concepts/metacognition.md).

### Self-healing

Watchdogs observe the agent loop; a policy decides what to do; the hook layer enforces the decision. `StallDetector`, `LoopDetector`, and `RegressionDetector` cover the three most common failure modes. A `FallbackModel` chain handles transient provider errors transparently.

```python
from orqest.healing import HealingConfig, FallbackModel
from orqest.workbench import Workbench

workbench = Workbench()
async with workbench.with_healing(HealingConfig(stall_timeout_s=30)):
    model = FallbackModel(["openai:gpt-4.1", "anthropic:claude-sonnet-4-6"])
```

See [Self-Healing](concepts/healing.md).

### Reflective optimization (GEPA)

Prompts and agent topologies can be evolved against a small gold set. The optimization is search-time only; nothing changes at runtime cost.

```python
from orqest.optimization import OptimizationRunner, OptimizationConfig, GoldExample

runner = OptimizationRunner(
    agent=agent,
    evaluator=my_metric,
    config=OptimizationConfig(generations=10),
)
result = await runner.run(gold=[GoldExample(input=..., expected=...) for ...])
runner.apply(result)
```

The same machinery evolves multi-agent topologies. See [Optimization](concepts/optimization.md) and [Topology Optimization](concepts/topology_optimization.md).

### Agents that spawn agents — and author their own tools

A planner LLM emits an `AgentSpec` (or a `GeneratedToolSpec`) as structured output. The factory hydrates it into a working agent; the sandbox compiles the generated tool into a pydantic-ai `Tool`. Generated tools can be persisted per user, so they survive across sessions.

```python
from orqest.autonomy import AgentFactory, MetaOrchestrator, ToolRegistry

meta = MetaOrchestrator(
    planner_agent,
    ToolRegistry(),
    default_model="openai:gpt-4.1",
)
result = await meta.solve("Find the top 3 AI papers this week and summarise each.")
```

Three sandbox tiers are available: in-process (opt-in, no isolation), subprocess (default, RLIMIT-bounded), and Docker (per-session container with an in-container FastMCP server). See [Runtime Agent Design](concepts/autonomy.md) and [Sandbox](concepts/sandbox.md).

### Cognitive memory typology

Memory is split into three kinds with separate retrieval strategies: **semantic** (facts), **episodic** (events), and **procedural** (skills with versioned implementations). Per-kind policies cover reliability decay on failure, TTL retention, and skill versioning.

```python
from orqest.memory import LocalMemoryStore, MemoryEntry, MemoryFilter, Skill

store = LocalMemoryStore(path="memory.db")
await store.store(MemoryEntry(
    memory_type="procedural",
    structured_content=Skill(trigger="refund a customer", steps=[...]),
))
hits = await store.recall(MemoryFilter(query="how do I issue a refund?", memory_type="procedural"))
```

The `MemoryStore` protocol is pluggable; the SQLite + FTS5 implementation is one option. See [Memory](concepts/memory.md).

### Composition primitives

Four orchestration shapes cover most multi-agent workflows. Each accepts agents, plain callables, or other primitives — they compose cleanly.

```python
from orqest import Pipeline, Parallel, Router, RefinementLoop

triage_then_solve = Pipeline([triage_agent, solver_agent])
broadcast        = Parallel([researcher, critic, summariser])
specialist       = Router(routes=[...], classifier=classifier_agent, fallback=generalist)
refine_until_ok  = RefinementLoop(agent=writer, evaluator=critic, confidence_threshold=0.85)
```

See [Orchestration](concepts/orchestration.md).

### Generative UI

Agents emit typed component specifications; the frontend resolves them into rendered UI. The first-party registry ships 17 components across three layers: primitives, declarative grammars (Vega, Mermaid, LaTeX), and a sandboxed HTML escape hatch.

```python
from orqest.ui import UIEmitter, ChartComponent

emitter = UIEmitter(workbench.event_bus)
emitter.init(ChartComponent(component_id="sales", data={"rows": []}))
emitter.delta("sales", op="append", path="data.rows", value={"q": "Q1", "v": 42})
```

See [Generative UI](concepts/generative_ui.md).

### MCP — client, server, auto-discovery

Orqest can consume MCP servers, expose itself as an MCP server, and discover new servers on demand. Discovery is gated by a `PermissionGate` that defaults to deny-all.

```python
from orqest.mcp import MCPServerManager, create_orqest_server

async with MCPServerManager(config) as mgr:
    tools = mgr.get_all_tools()

server = create_orqest_server(factory, registry, meta, default_model, api_key)
```

See [MCP](concepts/mcp.md).

### Observability

A single `EventBus` + `JSONTracer` pair, wired through `Workbench`, captures every tool invocation. An `sse_sidecar` helper streams events to the browser with replay, heartbeat, and ring-buffered backpressure.

See [Observability](concepts/observability.md) and [SSE Sidecar](concepts/sse-sidecar.md).

## A minimal working agent

```python
import asyncio
from pydantic import BaseModel
from orqest import load_config
from orqest.agents import BaseAgent, GlobalState


class Answer(BaseModel):
    text: str


class QAAgent(BaseAgent[GlobalState, Answer]):
    async def _run_implementation(self, state, **kwargs) -> Answer:
        result = await self.call_model(state.get_latest_message("user"), state)
        return result.output


async def main():
    cfg = load_config()
    agent = QAAgent(
        agent_name="qa",
        system_prompt="Answer concisely.",
        output_type=Answer,
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,
    )
    state = GlobalState()
    state.add_message("user", "What is the capital of France?")
    print((await agent.run(state)).text)


asyncio.run(main())
```

## Where to go next

- [Getting Started](getting-started.md) — installation, configuration, and a first multi-turn agent.
- [Notebooks](notebooks.md) — 12-notebook tour, recommended starting point for evaluating Orqest.
- **Composition**: [Agents](concepts/agents.md), [State & History](concepts/state-and-history.md), [Agent as Tool](concepts/agent-as-tool.md), [Streaming](concepts/streaming.md), [Orchestration](concepts/orchestration.md), [Hooks & Lifecycle](concepts/hooks-and-lifecycle.md), [Compound Tools](concepts/compound-tools.md), [Sub-Agent Tool](concepts/sub-agent-tool.md), [Execution Plan](concepts/execution-plan.md), [Session Persistence](concepts/session-persistence.md).
- **Autonomy**: [Runtime Agent Design](concepts/autonomy.md), [MCP](concepts/mcp.md).
- **Memory & Cognition**: [Memory](concepts/memory.md), [Metacognition](concepts/metacognition.md), [Reasoning](concepts/reasoning.md), [Optimization](concepts/optimization.md), [Topology Optimization](concepts/topology_optimization.md), [Web Tools](concepts/web-tools.md).
- **Production**: [Workbench](concepts/workbench.md), [Observability](concepts/observability.md), [SSE Sidecar](concepts/sse-sidecar.md), [Event Bus Hook](concepts/event-bus-publish-hook.md), [Self-Healing](concepts/healing.md), [Sandbox](concepts/sandbox.md), [Generative UI](concepts/generative_ui.md).
- **Tooling**: [Skills](concepts/skills.md) — the bundled `orqest` skill for agentic IDEs.
- [API Reference](api/config.md) — auto-generated from source.
- [Changelog](changelog.md).
