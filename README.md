# Orqest

**Typed agent primitives and orchestration on top of [pydantic-ai](https://ai.pydantic.dev)** — memory, autonomy, self-healing, metacognition, generative UI, MCP, and reflective optimization. All opt-in.

[![PyPI](https://img.shields.io/pypi/v/orqest.svg)](https://pypi.org/project/orqest/)
[![Python](https://img.shields.io/pypi/pyversions/orqest.svg)](https://pypi.org/project/orqest/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Orqest is not a framework with its own runtime, server, or UI. It's the plumbing you import to build one — composable batteries you pick à-la-carte. The agent loop stays yours.

```bash
pip install orqest
```

Requires **Python 3.12+**. Set `LLM_MODEL` and `LLM_API_KEY` (or pass them explicitly).

---

## Why Orqest

### Agents that know what they don't know

Every agent can return confidence, what it's uncertain about, and whether the task is outside its capability. Pluggable protocols — free (structured output), +1 call (self-rating), or +k calls (ensemble).

```python
from orqest.metacognition import StructuredOutputProtocol

enriched = await agent.run_enriched(state, confidence_protocol=StructuredOutputProtocol())
print(enriched.confidence, enriched.uncertainty_targets, enriched.capability_boundary)
# 0.42  ["population_figure"]  False
```

`RefinementLoop(confidence_threshold=0.85)` exits when the agent says it's confident. `MetaOrchestrator` re-decomposes subtasks when confidence drops below a threshold.

### Self-healing built in

Watchdogs observe; the policy decides; the hook layer enforces. Stalls, tool-call loops, and confidence regressions become typed `Detection` events. Models fail over transparently.

```python
from orqest.healing import HealingConfig, FallbackModel
from orqest.workbench import Workbench

workbench = Workbench()
async with workbench.with_healing(HealingConfig(stall_timeout_s=30)):
    model = FallbackModel(["openai:gpt-4.1", "anthropic:claude-sonnet-4-6"])
    # transient errors advance the chain; runaway tool loops abort cleanly
```

### Reflective optimization (GEPA)

Evolve prompts — and entire agent topologies — from a gold set. Search-time only; no runtime cost.

```python
from orqest.optimization import OptimizationRunner, OptimizationConfig, GoldExample

runner = OptimizationRunner(
    agent=agent,
    evaluator=my_metric,
    config=OptimizationConfig(generations=10),
)
result = await runner.run(gold=[GoldExample(input=..., expected=...) for ...])
runner.apply(result)  # dry-run by default; shows diff before mutating
```

Topology evolution uses the same machinery to evolve *which agents call which* — see [notebook 09](notebooks/09_topology_with_gepa.ipynb).

### Agents that spawn agents — and author their own tools

LLM emits an `AgentSpec` or a `GeneratedToolSpec`; the factory builds the agent, the sandbox compiles the tool. Generated tools are persisted per-user across sessions.

```python
from orqest.autonomy import AgentFactory, MetaOrchestrator, ToolRegistry

meta = MetaOrchestrator(planner_agent, ToolRegistry(), default_model="openai:gpt-4.1")
result = await meta.solve("Find the top 3 AI papers this week and summarize each.")
# Planner decomposes; specialist agents spawn; results aggregate.
```

Three sandbox tiers: in-process (opt-in unsafe), subprocess (default, RLIMIT-bounded), Docker (per-session container with an in-container FastMCP server).

### Cognitive memory typology

Semantic, episodic, procedural — each with its own retrieval strategy. Skills are versioned; reliability decays on failure; TTL prunes stale entries.

```python
from orqest.memory import LocalMemoryStore, MemoryEntry, MemoryFilter, Skill

store = LocalMemoryStore(path="memory.db")
await store.store(MemoryEntry(
    memory_type="procedural",
    structured_content=Skill(trigger="refund a customer", steps=[...]),
))
hits = await store.recall(MemoryFilter(query="how do I issue a refund?", memory_type="procedural"))
```

Pluggable `MemoryStore` Protocol — swap in pgvector or your own backend.

### Composition primitives

```python
from orqest import Pipeline, Parallel, Router, RefinementLoop

triage_then_solve = Pipeline([triage_agent, solver_agent])
broadcast        = Parallel([researcher, critic, summarizer])
specialist       = Router(routes=[...], classifier=classifier_agent, fallback=generalist)
refine_until_ok  = RefinementLoop(agent=writer, evaluator=critic, confidence_threshold=0.85)
```

Each primitive accepts agents, callables, or other primitives — they compose.

### Generative UI

Agents emit typed component specs; the frontend resolves. 17 first-party components across three layers (primitives, declarative grammars, sandboxed HTML).

```python
from orqest.ui import UIEmitter, ChartComponent

emitter = UIEmitter(workbench.event_bus)
emitter.init(ChartComponent(component_id="sales", data={"rows": []}))
emitter.delta("sales", op="append", path="data.rows", value={"q": "Q1", "v": 42})
```

### MCP — client, server, and auto-discovery

```python
from orqest.mcp import MCPServerManager, create_orqest_server

# Consume any MCP server — get pydantic-ai Tools out
async with MCPServerManager(config) as mgr:
    tools = mgr.get_all_tools()

# Or expose your agents as MCP tools to anyone else
server = create_orqest_server(factory, registry, meta, default_model, api_key)
```

Auto-discovery (`get_or_discover` + `DiscoveryHook`) is gated by `PermissionGate` — defaults to deny-all.

### Observability

```python
from orqest.observability import EventBus, JSONTracer, sse_sidecar

# Wire once; every tool emits tool.before / tool.after / tool.error
# sse_sidecar yields SSE strings with ring-buffered replay + heartbeat
```

---

## The smallest working agent

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

---

## Supported providers

`provider:model_id` format routes to the right SDK.

| Provider   | Example                              |
|------------|--------------------------------------|
| OpenAI     | `openai:gpt-4.1`                     |
| Anthropic  | `anthropic:claude-sonnet-4-6`        |
| Google     | `google:gemini-2.5-pro`              |
| OpenRouter | `openrouter:anthropic/claude-3.5-sonnet` |

## Learn

- **[Notebooks](notebooks/)** — *start here.* A 12-notebook tour from the cognitive substrate → meta-orchestrator → generative UI → orchestration → reasoning → optimization → topology evolution → runtime topology → dynamic tools → autonomous-coder combo.
- **[Concepts](https://kareemlsd.github.io/orqest/concepts/agents/)** — one doc per battery (24 in total).
- **[API Reference](https://kareemlsd.github.io/orqest/api/agents/)** — auto-generated from source.
- **[Benchmarks](benchmarks/)** — reproducible head-to-heads. Current: test-driven refinement loop beats single-shot by +17pp pass@1 (3-trial average).
- **[Examples](examples/)** — runnable per-primitive references.
- **[Bundled skill](orqest/skills/orqest/SKILL.md)** — install into an agentic IDE with `python -m orqest.skills install`. See [Skills](https://kareemlsd.github.io/orqest/concepts/skills/) on the docs site.

## Contributing

Issues and PRs welcome. New subsystems land as tracer-bullet, tests-first slices.

## License

[MIT](LICENSE)
