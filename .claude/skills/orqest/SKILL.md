---
name: orqest
description: Build Python agentic harnesses with the Orqest library on top of pydantic-ai. Use when integrating an AI agent into an existing application — interview the developer, walk the existing codebase, then pick the minimal Orqest surface (BaseAgent, Pipeline, Memory, MetaOrchestrator, Healing, Generative UI) that fits and wire it in. Includes the Polymath pattern for integrating with the Vercel AI SDK on a Next.js / React frontend (Data Stream Protocol for chat plus a parallel SSE sidecar for cognitive backbone events). Trigger whenever the user mentions Orqest, building an "agent" / "AI agent" / "agentic harness", adding AI / LLM features to an existing Python codebase, integrating an "AI sidebar" or "AI chat with tools" into a frontend, building a "research assistant" / "coding assistant" / "domain-specific agent", architecting a multi-agent system, or asks about pydantic-ai composition primitives — even if the word "Orqest" is not used.
---

# Orqest — Build Agentic Harnesses

Orqest is a Python **library** for building agentic harnesses on top of pydantic-ai. It is **not** a runtime, server, framework with its own UI, or workflow engine. It is the plumbing imported into an existing application to wire in agent capabilities. Polymath (`demo/polymath/` in the Orqest repo) is one consumer that exercises every primitive end-to-end.

> **The litmus test that governs every decision:**
> *"Core Orqest manages the shape and flow of intelligence; extensions manage the matter and action of the domain. Could a developer building a headless coding assistant use this without knowing what Polymath is?"*
>
> When in doubt, less is more. **Pick the smallest surface that fits.**

## Operating Procedure (REQUIRED — follow in order)

When a developer asks for help adding agent capabilities to an application, or building a new agentic system using Orqest, follow this loop. **Do not skip steps. Skipping discovery is the #1 failure mode.**

### Step 1 — Discovery: interview the developer

Read `references/discovery_questions.md` and work through the question batches with the developer via the IDE's question UI. The questions span: application context, agentic intent, inputs/outputs, tools, state/memory, reliability, cost, observability, UI, auth, deployment.

**Hard rule:** every Orqest component proposed in Step 3 must trace back to an answer the developer gave in this step. If you can't cite the answer, don't include it.

### Step 2 — Codebase Walk: read the existing stack

Read `references/codebase_walk.md` for stack-specific grep / read patterns (FastAPI, Django, Next.js, Node backend, CLI, background workers). Identify framework, auth layer, data layer, async posture, observability, frontend, CI/test setup. Conclude with a 5–7 line summary the developer can correct.

### Step 3 — Minimal Surface Selection

Apply the lookup table at the top of `references/recipes.md`: application shape → minimal Orqest surface. Memory / healing / metacognition / generative UI / orchestration are each **opt-in**. Default-deny everything; add a layer only when a Phase A answer demands it.

Polymath uses every layer because it is the framework's flagship demo. Most consumer apps need 20–40% of it.

### Step 4 — Integration Plan

Present a written plan to the developer (a few paragraphs covering: chosen surface and the Phase A answers that justify each component; module layout in their existing codebase; integration points; expected event flow). **Get approval before writing code.**

### Step 5 — Build (tracer-bullet)

Implement the smallest end-to-end working slice first. Iterate from there. The relevant pattern lives in `references/recipes.md` — eight named recipes covering Conversational, Pipeline, Parallel, Refinement, Memory-backed, Multi-agent (MetaOrchestrator), Production (healing + fallback), and Generative UI.

If the consumer wants a Vercel AI SDK + Orqest frontend (Polymath pattern), read `references/ai_sdk_integration.md` and use the templates in `assets/frontend_hooks/` and `assets/agent_module_template/`.

The script `scripts/scaffold_agent.py` lays down the agent module skeleton into a target project — run it with `--surface basic|workbench-events|refinement|orchestrated|production`.

### Step 6 — Document (REQUIRED OUTPUT)

After the harness is built, produce an `AGENT_HARNESS.md` in the consumer project (or `docs/agent_harness.md` if the project already has a `docs/`). Use the structure in `references/agent_harness_template.md` — this is the **extensibility playbook for the harness you just built**, the contract for the next session (you, a different LLM, or a human) to extend without re-discovering the architecture.

## Core mental model

Eight composable batteries, opt-in:

```
Workbench (memory + tracer + event_bus + ui_registry)
├── Composition: Pipeline | Parallel | Router | RefinementLoop
├── Cognition:   EnrichedOutput | ConfidenceProtocol | Watchdog | RecoveryAction | FallbackModel
├── Memory:      MemoryStore (semantic | episodic | procedural)
├── UI:          UIComponentSpec | UIEmitter | ComponentRegistry
├── Autonomy:    AgentSpec | AgentFactory | ToolRegistry | MetaOrchestrator
├── Observ.:     Span | Tracer | EventBus | sse_sidecar
├── Hooks:       ToolHook | HookRunner | HookDecision
└── Agents:      BaseAgent[StateT, OutputT] | GlobalState
```

For the public API by submodule (the import paths a consumer should use), read `references/api_surface.md`.

## Coding discipline (REQUIRED)

All Orqest harness code must follow Pragmatic Programmer rules: orthogonality, DRY, YAGNI, ETC ("Easy to Change"), shy code, crash early, design by contract, tracer bullets. Read `references/anti_patterns.md` for the load-bearing rules and the do-NOT list. Inline summary:

- **Async-first.** Every agent path is `async def`; bridge to sync only at framework boundaries.
- **Pydantic everywhere.** State, output, configs (frozen dataclass), memory entries — all Pydantic.
- **Generic typing.** `BaseAgent[StateT, OutputT]`, `Pipeline[InputT, OutputT]`. Always parameterized.
- **Single config knob.** Every cross-cutting concern (model, API key, memory backend, healing toggle) lives behind one configuration source.
- **Constructor injection. No module-level state.** `Workbench` / `EventBus` / `Tracer` are per-session.
- **No what-comments.** Names already do that. Comments only for WHY.
- **Match the host app's conventions.** If the app uses Pylint, use Pylint. If it has its own logging convention, route Orqest events through it. Do not impose Orqest's conventions on the consumer.

## Extending Orqest itself

If a consumer needs a primitive Orqest doesn't ship (a new Watchdog, a new ConfidenceProtocol, a new memory backend, a custom `UIComponentSpec`, etc.) — read `references/extension_patterns.md`. It maps each extension point to the canonical pattern (which Protocol to implement, where to put it, how to test).

## Reference index

| Reference | When to read |
|-----------|--------------|
| `references/discovery_questions.md` | **Step 1 (always).** Question checklist for the interview. |
| `references/codebase_walk.md` | **Step 2 (always).** Grep / read patterns per host stack. |
| `references/recipes.md` | **Step 3-5.** Eight named patterns with code, assumptions, integration points, "skip if". |
| `references/ai_sdk_integration.md` | **When the frontend uses Vercel AI SDK** (Next.js/React). The Polymath pattern: chat via Data Stream Protocol + parallel SSE sidecar for cognitive backbone events + ui.\<type\> dispatch + metacognition badge + healing toasts + takeover dialog. |
| `references/agent_harness_template.md` | **Step 6 (always).** The required output structure for `AGENT_HARNESS.md` in the consumer project. |
| `references/api_surface.md` | When you need the import path for a specific Orqest type. The 18 root re-exports plus documented submodule paths. |
| `references/anti_patterns.md` | When proposing a non-trivial design decision. The rules + the do-NOT list. |
| `references/extension_patterns.md` | When the consumer needs a primitive Orqest doesn't ship. Ten named extension patterns. |

## Asset index

| Asset | What it is |
|-------|------------|
| `assets/agent_module_template/` | Python boilerplate (`agent.py`, `types.py`, `tools.py`, `route.py`) — copy and rename into the consumer project. |
| `assets/frontend_hooks/` | React hooks extracted from Polymath (`useSidecar.ts`, `useMetacognition.ts`, `useHealingEvents.ts`, `useUIComponents.ts`) — copy into `frontend/src/hooks/` for AI SDK integration. |

## Script index

| Script | Purpose |
|--------|---------|
| `scripts/scaffold_agent.py` | Lay down the agent module skeleton into a target project. `python scripts/scaffold_agent.py --app-dir ./myapp --name orders_summary --surface basic` |

## Anti-patterns (top three)

1. **Skipping discovery.** Jumping straight to code without the Phase A questionnaire produces over-engineered harnesses (MetaOrchestrator + memory + healing for what should have been a single BaseAgent). **Always run Step 1 first.**
2. **Adding components the application doesn't need.** Memory, healing, metacognition, generative UI, orchestration are each opt-in. If discovery didn't surface a reason for it, leave it out.
3. **Imposing Orqest's conventions on the host app.** The agent code conforms to the existing app's lint config, logging convention, error-handling style. Orqest is the library; the host is the application.

For the full list, read `references/anti_patterns.md`.
