# Orqest

A Python library for building **agentic harnesses** on top of [pydantic-ai](https://ai.pydantic.dev). Not an agent framework with a runtime, server, or UI of its own — Orqest ships the plumbing you import to build those: typed agents, composition primitives, lifecycle hooks, memory typology, runtime agent design, metacognition, self-healing, and generative UI. All opt-in.

> **Status:** v0.4.0. The five novel cognitive-substrate features have shipped (2026-04-25): runtime agent design, cognitive memory typology, metacognition primitives, self-healing primitives, generative UI. `[0.3.0]` was the reconcile pass — code and docs brought into honest agreement; `[0.4.0]` is the advance pass — the preview tier finished into Tier 1. Test count: 670.

## Install

Requires **Python 3.12+**.

```bash
pip install orqest
# or
uv pip install orqest
```

Create a `.env` file (or set the equivalent env vars):

```bash
LLM_API_KEY=your_key_here
LLM_MODEL=openai:gpt-4.1
```

## Quickstart

The smallest working agent — 10 lines of useful code:

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
    config = load_config()
    agent = QAAgent(
        agent_name="qa",
        system_prompt="Answer concisely.",
        output_type=Answer,
        model=config.llm_model,
        api_key=config.llm_api_key,
    )
    state = GlobalState()
    state.add_message("user", "What is the capital of France?")
    print((await agent.run(state)).text)


asyncio.run(main())
```

## What Orqest gives you

Eight composable batteries — **opt-in**, picked à-la-carte per application:

- **Composition** — `Pipeline`, `Parallel`, `Router`, `RefinementLoop`. Sequence agents, fan out + merge, route by classifier, iterate until "good enough."
- **Memory** — `LocalMemoryStore` (SQLite + FTS5, or embedding-cosine recall via a pluggable embedder) with typed `semantic` / `episodic` / `procedural` retrieval. Per-kind policy: reliability decay, TTL retention, skill versioning. Pluggable `MemoryStore` Protocol for production backends.
- **Autonomy** — `AgentSpec` + `AgentFactory` + `ToolRegistry` + `MetaOrchestrator`. Agents that decompose goals and spawn specialists at runtime.
- **Metacognition** — `EnrichedOutput[OutputT]` carrying `confidence`, `uncertainty_targets`, `capability_boundary`. Three pluggable `ConfidenceProtocol` strategies (free / +1 call / +k calls). Agents that know what they don't know.
- **Self-healing** — `Watchdog` Protocol + `StallDetector` / `LoopDetector` / `RegressionDetector`. `RecoveryAction` discriminated union → `HookDecision` flow. `FallbackModel` for transparent provider failover.
- **Generative UI** — `UIComponentSpec[T]` typed components — 17 across 3 layers: compositional primitives (Plan, Chart, Table, Form, TakeoverDialog, Layout, Text, Markdown, Image, Badge, Button, Input), declarative grammars (Vega, Mermaid, Latex, JsonViewer), and a sandboxed HTML escape hatch. Agents emit; frontend resolves.
- **Observability** — `EventBus`, `JSONTracer`, `sse_sidecar` (with replay + heartbeat + ring buffer). Wire once, every tool emits.
- **MCP** — client (`MCPServerManager`) + server (`create_orqest_server`) + auto-discovery (`get_or_discover` + `DiscoveryHook` + `PermissionGate`).

## Building an application

**Read [`SKILLS.md`](SKILLS.md) first.** It's the playbook for integrating Orqest into an existing codebase: discovery questions to ask the developer, codebase-walk patterns to identify the existing stack, minimal-surface selection rules, eight pattern recipes, and an end-to-end FastAPI walkthrough. Designed for LLM coding assistants (Claude Code, Cursor) and human developers alike.

The flagship reference consumer is [`demo/polymath/`](demo/polymath/) — every Orqest battery lit up end-to-end (chat + dockview workspace + sub-agent roster + memory typology + cognitive gutter + healing toasts + generative UI tabs).

## Supported model providers

`provider:model_id` format routes to the right SDK. The full `pydantic-ai` dependency bundles every provider SDK; the lazy import is defensive.

| Provider | Format | Example |
|----------|--------|---------|
| OpenAI | `openai:model_id` | `openai:gpt-4.1` |
| Anthropic | `anthropic:model_id` | `anthropic:claude-sonnet-4-6` |
| Google | `google:model_id` | `google:gemini-2.5-pro` |
| OpenRouter | `openrouter:model_id` | `openrouter:anthropic/claude-3.5-sonnet` |

## Documentation

- **[SKILLS.md](SKILLS.md)** — how to build with Orqest (discovery → codebase walk → minimal surface → recipes)
- **[Concepts](https://kareemlsd.github.io/orqest/concepts/agents/)** — agents, state, composition, memory, metacognition, healing, generative UI
- **[API Reference](https://kareemlsd.github.io/orqest/api/agents/)** — auto-generated from source
- **[Examples](examples/)** — runnable per-primitive demos (basic agent → streaming → pipeline → refinement → memory → observability)
- **[CLAUDE.md](.claude/CLAUDE.md)** — agent-instructions ground truth
- **[ARCHITECTURE.md](.claude/ARCHITECTURE.md)** — extensibility playbook for contributors
- **[VISION.md](.claude/VISION.md)** — strategic frame for the cognitive-substrate goal
- **[Changelog](CHANGELOG.md)**

## Contributing

Contributions welcome. Read [`.claude/PRINCIPLES.md`](.claude/PRINCIPLES.md) (Pragmatic Programmer rules — canonical for this codebase) and [`.claude/ARCHITECTURE.md`](.claude/ARCHITECTURE.md) (each subsystem documents how to extend it). Open an issue or PR; new subsystems land as tracer-bullet tests-first slices.

## License

[MIT](LICENSE)
