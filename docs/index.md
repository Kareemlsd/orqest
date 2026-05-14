# Orqest

A Python library for building **agentic harnesses** on top of [pydantic-ai](https://ai.pydantic.dev). Not an agent framework with a runtime, server, or UI of its own — Orqest ships the plumbing you import to build those: typed agent primitives, orchestration, lifecycle hooks, a cognitive memory typology, runtime agent design, metacognition, self-healing, and generative UI. All opt-in.

> **Status:** v0.4.0. The five novel cognitive-substrate features have shipped — runtime agent design, cognitive memory typology, metacognition primitives, self-healing primitives, generative UI. The `[0.3.0]` reconcile pass brought code and docs into honest agreement; the `[0.4.0]` advance pass finished the preview tier into Tier 1.

## What Orqest gives you

Eight composable batteries — **opt-in**, picked à-la-carte per application:

- **Composition** — `Pipeline`, `Parallel`, `Router`, `RefinementLoop`. Sequence agents, fan out and merge, route by classifier, iterate until "good enough."
- **Memory** — `LocalMemoryStore` (SQLite + FTS5, or embedding-cosine recall via a pluggable embedder) with typed `semantic` / `episodic` / `procedural` retrieval, per-kind reliability decay, TTL retention, and skill versioning.
- **Autonomy** — `AgentSpec` + `AgentFactory` + `ToolRegistry` + `MetaOrchestrator`. Agents that decompose a goal and spawn the specialists to do it, at runtime.
- **Metacognition** — `EnrichedOutput[OutputT]` carrying `confidence`, `uncertainty_targets`, `capability_boundary`. Three pluggable `ConfidenceProtocol` strategies (free / +1 call / +k calls). Agents that know what they don't know.
- **Self-healing** — `Watchdog` + `StallDetector` / `LoopDetector` / `RegressionDetector`, the `RecoveryAction` → `HookDecision` flow, and `FallbackModel` for transparent provider failover.
- **Generative UI** — `UIComponentSpec[T]` typed components across three layers. Agents emit; the frontend resolves.
- **Observability** — `EventBus`, `JSONTracer`, `sse_sidecar` (with replay + heartbeat + ring buffer). Wire once, every tool emits.
- **MCP** — client (`MCPServerManager`) + server (`create_orqest_server`) + auto-discovery, gated by an explicit `PermissionGate`.

`BaseAgent[StateT, OutputT]` is the typed, async-first foundation underneath all of it: define your state and output models, implement `_run_implementation()`, done. `Workbench` bundles memory + tracer + event bus + UI registry into one container you pass around.

## Quick Start

```python
import asyncio
from pydantic import BaseModel, Field
from orqest import load_config
from orqest.agents import BaseAgent, GlobalState


class SummaryOutput(BaseModel):
    summary: str = Field(description="A concise summary")
    key_points: list[str] = Field(description="Main ideas")


class SummaryAgent(BaseAgent[GlobalState, SummaryOutput]):
    async def _run_implementation(self, state: GlobalState, **kwargs) -> SummaryOutput:
        user_message = state.get_latest_message("user")
        result = await self.call_model(user_message, state)
        return result.output


async def main():
    config = load_config()
    agent = SummaryAgent(
        agent_name="summarizer",
        system_prompt="Summarize the user's message concisely.",
        output_type=SummaryOutput,
        model=config.llm_model,
        api_key=config.llm_api_key,
    )

    state = GlobalState()
    state.add_message("user", "Explain quantum computing in simple terms.")
    output = await agent.run(state)
    print(output.summary)


asyncio.run(main())
```

For multi-agent workflows, compose agents with orchestration primitives:

```python
from orqest.orchestration import Pipeline

pipeline = Pipeline([research_agent, draft_agent, review_agent], name="content")
result = await pipeline.run("Write about quantum computing")
```

## Documentation

- [Getting Started](getting-started.md) — installation, configuration, and your first agent
- **Composition** — [Agents](concepts/agents.md), [State & History](concepts/state-and-history.md), [Orchestration](concepts/orchestration.md), [Hooks & Lifecycle](concepts/hooks-and-lifecycle.md), [Compound Tools](concepts/compound-tools.md), [Sub-Agent Tool](concepts/sub-agent-tool.md), [Execution Plan](concepts/execution-plan.md)
- **Autonomy** — [Runtime Agent Design](concepts/autonomy.md), [MCP](concepts/mcp.md)
- **Memory & Cognition** — [Memory](concepts/memory.md), [Metacognition](concepts/metacognition.md), [Web Tools](concepts/web-tools.md)
- **Production** — [Workbench](concepts/workbench.md), [Observability](concepts/observability.md), [SSE Sidecar](concepts/sse-sidecar.md), [Self-Healing](concepts/healing.md), [Generative UI](concepts/generative_ui.md)
- [API Reference](api/config.md) — auto-generated from source
- [Changelog](changelog.md) — version history
