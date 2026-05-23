---
name: orqest
description: Building agentic AI systems with Orqest — a Python framework on top of pydantic-ai that ships typed agent primitives, four orchestration shapes (Pipeline / Parallel / Router / RefinementLoop), cognitive memory (semantic / episodic / procedural), runtime-spawned topologies (MetaOrchestrator + AgentFactory), dynamic tool spawning, self-healing watchdogs, metacognition (confidence-aware output), generative UI, MCP client + server, and observability. Trigger when the project imports from `orqest`, when composing agents into pipelines or routers, when designing memory-backed or persistent-roster agents, when wrapping agents as tools (`SubAgentTool`, `as_tool`), when wiring `HookRunner`/`HookDecision`, when building multi-agent systems where the topology isn't fixed at build time, or when the user mentions Orqest, BaseAgent, Workbench, MetaOrchestrator, RefinementLoop, or similar Orqest primitives. Skip when: the project uses LangGraph / CrewAI / AutoGen / Semantic Kernel instead, or when the question is about pydantic-ai in isolation (no Orqest imports in the codebase), or for generic Python questions unrelated to agents.
---

# Orqest

Orqest is a **Python library** that wraps pydantic-ai with typed orchestration, memory, autonomy, healing, metacognition, MCP, observability, and generative-UI primitives. It is not a framework you live inside — it's plumbing you import.

## The litmus test

> *Core Orqest manages the **shape and flow** of intelligence; extensions manage the **matter and action** of the domain. Could a developer building a headless coding assistant use this primitive without knowing what the consuming app does?*

When in doubt: pick the smallest surface that fits.

## Decision tree — which primitive for which job

| You want to… | Reach for | Deep dive |
|---|---|---|
| Run one agent | `BaseAgent[StateT, OutputT]` | (this file) |
| Run agent A → agent B → agent C | `Pipeline` | `references/orchestration.md` |
| Run A and B concurrently and merge | `Parallel` | `references/orchestration.md` |
| Dispatch on input shape or LLM classifier | `Router` | `references/orchestration.md` |
| Iterate until an evaluator says "good enough" | `RefinementLoop` | `references/orchestration.md` |
| Hand an agent A to agent B *as a tool* | `as_tool()` (stateless) or `SubAgentTool` (stateful, evaluator-driven) | `references/orchestration.md` |
| Persist facts/events/skills across sessions | `LocalMemoryStore` + `Workbench` | `references/memory.md` |
| Let an LLM design the agent topology at runtime | `MetaOrchestrator` + `AgentFactory` + `ToolRegistry` | `references/autonomy.md` |
| Let an LLM **author a new tool's implementation** at runtime | `GeneratedToolSpec` + `DynamicToolFactory` + a `Sandbox` | `references/autonomy.md` |
| Get confidence + uncertainty + capability-boundary signals out of an agent | `EnrichedOutput` + `ConfidenceProtocol` | `references/metacognition.md` |
| Detect stalls / loops / confidence-regressions and recover | `HealingRunner` + watchdogs + `FallbackModel` | `references/healing.md` |
| Stream typed UI components alongside the agent's text | `UIEmitter` + first-party components | `references/generative-ui.md` |
| Connect to MCP servers / expose Orqest as MCP | `MCPServerManager` / `create_orqest_server` | `references/mcp.md` |
| Evolve prompts or topology with GEPA / ADAS | `orqest.optimization.OptimizationRunner` / `MetaAgentSearch` | `references/optimization.md` |
| Safely execute LLM-authored Python | `SubprocessSandbox` / `DockerSandbox` + `GeneratedToolSpec` | `references/sandbox.md` |
| Trace + emit events for observability | `Workbench` (bundles `JSONTracer` + `EventBus`) | `docs/concepts/observability.md` |

**When NOT to reach for the autonomy layer:** if you know the decomposition at build time, write a `Pipeline` of fixed agents. `MetaOrchestrator` adds a planner LLM call per request — pay it only when the decomposition itself is the hard part. Same litmus applies to `RuntimeTopologyDesigner`.

## Wire-up patterns

The five patterns below cover ~80% of real Orqest usage. Each is paste-ready.

### 1. A single agent

```python
import asyncio
from pydantic import BaseModel
from orqest.agents import BaseAgent, GlobalState


class Answer(BaseModel):
    reasoning: str
    answer: str


class Researcher(BaseAgent[GlobalState, Answer]):
    name = "researcher"
    system_prompt = "You research questions and answer concisely."
    output_type = Answer


async def main():
    agent = Researcher(model="openai:gpt-4.1", api_key="sk-...")
    state = GlobalState()
    state.add_user_message("What is the half-life of caesium-137?")
    result = await agent.run(state)
    print(result.output.answer)


asyncio.run(main())
```

`BaseAgent` is `BaseAgent[StateT, OutputT]` — always specify both type parameters. `GlobalState` carries both app-level message dicts (for persistence) and pydantic-ai `ModelMessage` history (for the next run); they're kept in sync automatically.

### 2. A pipeline of agents and pure functions

```python
from orqest.orchestration import Pipeline, StepConfig, ErrorStrategy

async def clean(text: str) -> str:
    return text.strip().lower()

pipeline = Pipeline(
    [
        clean,                                                          # async fn → FunctionStep
        (researcher_agent, StepConfig(on_error=ErrorStrategy.RETRY)),   # BaseAgent → AgentStep
        summariser_agent,                                               # default ErrorStrategy.STOP
    ],
    name="research-then-summarise",
)
result = await pipeline.run("quantum computing")
```

Steps are auto-coerced: `BaseAgent` → `AgentStep`, async callable → `FunctionStep`, anything implementing `Step` is used as-is. `ErrorStrategy` is `STOP` (default), `SKIP`, or `RETRY`.

### 3. An agent used as another agent's tool

Two flavors — pick based on whether you need state-update + evaluator feedback.

```python
# Stateless: the sub-agent runs once per invocation, no state carried back.
from orqest.agents import as_tool
tool = as_tool(researcher_agent, name="research", description="Look up facts.")
caller_agent.add_tool(tool)
```

```python
# Stateful + evaluator-driven: SubAgentTool refines until quality passes.
from orqest.compound import SubAgentTool

reviewer = SubAgentTool(
    agent=writer_agent,
    executor=lambda state, output: output.draft,    # how to extract result
    state_updater=lambda state, output: state,      # how to fold back
    evaluator=quality_evaluator,                    # optional refinement
    max_iterations=3,
)
```

Use `as_tool` 90% of the time. Reach for `SubAgentTool` when you need quality-gated refinement *inside* a tool call.

### 4. Memory + observability via Workbench

`Workbench` is the one container that bundles `MemoryStore + Tracer + EventBus + ui_registry + recent-events buffer`. Plumb it once; pass it around.

```python
from orqest import Workbench
from orqest.memory import LocalMemoryStore, MemoryConfig, PerKindConfig, MemoryEntry

wb = Workbench(
    user_id="alice",
    session_id="2026-05-23-001",
    memory=LocalMemoryStore(
        config=MemoryConfig(
            local_db_path="~/.app/memory.db",
            semantic=PerKindConfig(decay_on_failure=0.7, prune_below=0.1),
            episodic=PerKindConfig(ttl_days=90),
            procedural=PerKindConfig(version_on_edit=True),
        ),
    ),
)

# Store + recall
await wb.memory.store(MemoryEntry(
    content="User prefers terse responses.",
    memory_type="semantic",
    source_agent="onboarding",
))
hits = await wb.memory.recall("response style", k=3)
```

The three memory types map to cognitive primitives: **semantic** = facts, **episodic** = events, **procedural** = skills (sub-agent specs, tool-sequence recipes). Pass `embedder=...` to `LocalMemoryStore` for cosine-similarity semantic recall; without one it falls back to FTS5/LIKE.

### 5. Goal-driven runtime topology (autonomy layer)

When the decomposition isn't known at build time:

```python
from orqest.autonomy import AgentFactory, MetaOrchestrator, ToolRegistry
from orqest.metacognition import MetacognitionConfig

registry = ToolRegistry()
registry.register(get_logs)
registry.register(compute_p95)

factory = AgentFactory(registry=registry, default_model="openai:gpt-4.1", api_key="sk-...")

orchestrator = MetaOrchestrator(
    planner=planner_agent,                       # outputs TaskDecomposition
    factory=factory,
    registry=registry,
    memory=wb.memory,                            # persists specs as procedural Skills
    bus=wb.event_bus,
    metacognition=MetacognitionConfig(redecompose_threshold=0.5, max_redecompositions=2),
    max_subtasks=10,
    max_spawn_depth=3,
)
result = await orchestrator.solve("Investigate the Q3 latency regression and propose a remediation")
```

The planner emits an `AgentSpec` per subtask, the factory hydrates it into a `DynamicAgent`, the orchestrator runs it through the hook chain. Persisted specs survive across sessions — yesterday's "rate-limit analyst" shows up today already trained.

## Pitfalls — the ones that bite

- **`BaseAgent` requires both type params.** `BaseAgent[GlobalState, MyOutput]`, never bare `BaseAgent`. The type system is load-bearing.
- **Async-first, everywhere.** Every agent-touching path is `async def`. Don't reach for `asyncio.run` inside library code; let the caller drive the loop.
- **Hooks are fire-and-forget at the *compound* boundary.** `HookRunner` wraps `CompoundTool` / `SubAgentTool` / `MetaOrchestrator` subtask calls. It does NOT intercept pydantic-ai's internal tool dispatch. If you need per-tool intercepts inside the agent loop, that's not what hooks are for.
- **Don't share a `MetaOrchestrator` across requests.** It owns `_spawned_agents` per run; reuse leaks state across users.
- **`LocalMemoryStore` is best-effort.** Failures log at WARNING and never raise. Don't treat a successful `store()` call as durable confirmation; treat memory as a cache with reliability decay.
- **`output_schema` vs `output_type` on `AgentSpec` is exactly-one-of.** Use `output_type=MyPydanticModel` for code-side specs; use `output_schema=<dict>` for LLM-emitted or persisted-to-disk specs. Setting both raises; setting neither raises.
- **`add_tool` invalidates the cached pydantic-ai Agent.** Safe to call between runs. In-flight `agent.run()` calls don't see the new tool — they captured the tool list at start.
- **Healing's `RegressionDetector` needs metacognition.** It subscribes to `metacognition.confidence` events. With no metacog feed, it silently no-ops. That's by design — the two batteries cross-couple but degrade gracefully alone.

## Model resolution

`LLM_MODEL=provider:model_id` everywhere — `openai:gpt-4.1`, `anthropic:claude-sonnet-4-6`, `google:gemini-2.0-flash`, `openrouter:...`. `orqest.utils.llm_model.resolve_model()` dispatches to the lazily-imported provider. For tests, pass `model=TestModel()` directly — every constructor accepts an explicit model override.

## Public API surface (root re-exports)

```python
from orqest import (
    # Config
    OrqestConfig, load_config, get_default_config,
    # Hooks
    HookRunner, ToolHook, HookDecision, Continue, Skip, Redirect, Abort, HookAbortError,
    # Orchestration
    Pipeline, Parallel, Router, RefinementLoop,
    # Workbench + Plan
    Workbench, ExecutionPlan, PlanStatus, PlanSubtask, PlanTask,
    # Vision features
    EnrichedOutput, MetacognitionConfig, HealingConfig,
    OptimizationConfig, MetaAgentConfig,
)
```

Everything else lives in submodules — keep the root namespace lean:

```python
from orqest.agents import BaseAgent, GlobalState, as_tool
from orqest.orchestration import Pipeline, Parallel, Router, RefinementLoop, Route, StepConfig, ErrorStrategy
from orqest.memory import LocalMemoryStore, MemoryEntry, MemoryFilter, Skill
from orqest.autonomy import AgentSpec, ToolSpec, GeneratedToolSpec, AgentFactory, ToolRegistry, MetaOrchestrator, DynamicToolFactory
from orqest.observability import EventBus, JSONTracer, sse_sidecar
from orqest.compound import SubAgentTool, SubAgentResult
from orqest.metacognition import StructuredOutputProtocol, LLMSelfRatingProtocol, EnsembleProtocol, MetacognitionHook
from orqest.healing import HealingRunner, StallDetector, LoopDetector, RegressionDetector, FallbackModel
from orqest.ui import UIComponentSpec, UIEmitter, default_registry
from orqest.sandbox import SubprocessSandbox, InProcessSandbox, Sandbox
```

## Where to read more

- **Compressed judgment-layer references (load only what's relevant):** `references/orchestration.md`, `memory.md`, `autonomy.md`, `healing.md`, `metacognition.md`, `mcp.md`, `optimization.md`, `generative-ui.md`, `sandbox.md`.
- **Canonical concept docs (full API + edge cases):** `docs/concepts/<name>.md` — every reference links back here for depth. Use these when the reference says "for full reference, read…".
- `CLAUDE.md` — agent-instructions ground truth (file layout, conventions, public API)
- `notebooks/` — 12-notebook tour: cognitive substrate → meta-orchestrator → generative UI → orchestrated workflow → reasoning → optimization → topology search → runtime topology → dynamic tools → autonomous-coder combo
- `examples/01_…/` through `09_…/` — runnable per-primitive references
