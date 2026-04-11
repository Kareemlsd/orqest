# Roadmap

## Core Problem

Building a single agent is easy. Going from one agent to multiple agents collaborating
requires a massive jump in infrastructure complexity — context management, execution
patterns, error handling, debugging — none of which is the developer's actual problem.

Orqest's goal: **make the jump from 1 agent to N agents incremental, not architectural.**

## Design Principles

1. An agent is defined once. How it participates — as a conversational agent, a pipeline step, or a tool — is determined by how it's composed, not by rewriting the agent.
2. Core Orqest manages the *shape* and *flow* of intelligence; Extensions manage the *matter* and *action* of the domain.
3. Ship pure Python first. Optimize with Rust only after profiling confirms bottlenecks.

---

## Phase 1 — Composition Primitives ✅ COMPLETE

### 1a. Orchestration ✅

- `Pipeline` — sequential step execution with STOP/SKIP/RETRY error strategies
- `Parallel` — concurrent execution with merge strategies and timeout
- `Router` — rule-based and LLM-driven conditional routing with fallback
- `RefinementLoop` — iterative refinement with evaluator feedback and convergence
- `Step` protocol — unified interface for agents and pure async functions

### 1b. Core Uplift ✅

- `HookRunner` + `ToolHook` — fire-and-forget lifecycle hooks
- `BaseSessionState` — serializable session state with ModelMessages persistence
- `CompoundTool` — agent→execute→update pattern with hook integration

---

## Phase 2 — Memory Architecture 🔄 IN PROGRESS

**Goal:** Agents that learn, remember, and forget intelligently across sessions.

### Memory Protocol
- `MemoryStore` protocol: `store()`, `recall()`, `forget()`
- `MemoryEntry` model: content, type (semantic/episodic), confidence, reliability_score
- Separate `MemoryConfig` (orthogonal to `OrqestConfig`)

### Backends
- Local SQLite + sqlite-vec (zero-config development)
- Supabase pgvector + Postgres (production, with RLS)
- Both as optional extras: `pip install orqest[local-memory]` / `orqest[supabase]`

### Self-Healing
- Reliability decay: `score = base * (0.7 ^ failure_count)`
- Pruning: memories below 0.1 reliability removed during maintenance
- Memory operations are best-effort (never block agent execution)

### Integration
- Memory is a service on state, not a BaseAgent constructor parameter
- ContextManager stays orthogonal (within-session vs cross-session are different concerns)

---

## Phase 3 — Autonomy (Dynamic Agent Spawning)

**Goal:** Orchestrator can design and spawn new agents at runtime.

### Core Components
- `AgentSpec` — serializable agent definition (prompt, output schema, tools, constraints)
- `AgentFactory` — hydrates spec into live agent via `pydantic.create_model()`
- `ToolRegistry` — central tool discovery (pre-registered + MCP + dynamic)
- `MetaOrchestrator` — self-spawning loop: decompose → find/create → execute → learn
- `ToolSandbox` — protocol for safe execution of generated tool code

### Safety
- Policy inheritance (global constraints flow to children)
- Resource quotas (token budgets per spawned agent)
- Depth limits (max nesting of spawned agents)
- Human-in-the-loop gate for dangerous permissions

### Learning
- Successful AgentSpecs saved to episodic memory for reuse
- Failed specs penalized via reliability_score decay

---

## Phase 4 — Observability

**Goal:** When agent 4 in a pipeline produces bad output, trace the root cause.

- Lightweight `Span` and `Tracer` protocol (zero deps by default)
- Optional `orqest[otel]` for OpenTelemetry export
- In-process `EventBus` (subsumes HookRunner)
- Pipeline events flow through bus automatically

---

## Phase 5 — MCP Server (Claude Code Integration)

**Goal:** Claude Code builds agentic software using orqest as a tool.

- FastMCP server: `create_agent`, `run_agent`, `spawn_agent`, `list_agents`
- Run as: `python -m orqest.mcp.server`
- Dynamic Pydantic model construction from JSON Schema for `create_agent`

---

## Phase 6 — Resilience

**Goal:** Autonomous systems that detect and repair their own degradation.

- Watchdog: loop detection as history processor
- Diagnostic retry: error→diagnosis→enriched retry pattern
- Resource quotas enforcement
- Policy inheritance for spawned agents

---

## Future — Rust Engine

After profiling confirms bottlenecks:
- Token counting (CPU-bound, replace heuristic with real tokenization)
- History processing (10K+ message list transforms)
- Parallel execution engine (concurrency safety via ownership model)
- Event bus (high-throughput emission)
- Interop: PyO3 + maturin. `pip install orqest` works without Rust compiler.

---

## What's NOT in Scope

- Domain-specific agents (user builds those, orqest provides building blocks)
- Visual UI / drag-and-drop builder (separate package if ever needed)
- Custom LLM inference (we use pydantic-ai for all model interaction)
- Competing with pydantic-ai — we build on top, not around

## Current Status

- [x] BaseAgent[StateT, OutputT] with typed generics
- [x] Multi-provider model routing
- [x] Config without import-time side effects
- [x] History processing (pure functions, turn integrity)
- [x] GlobalState + BaseSessionState (with serialization)
- [x] Streaming (call_model_stream, stream_output, stream_events)
- [x] Multi-modal input support
- [x] Token-aware context management (ContextManager)
- [x] Tool result budgeting (budget_tool_results)
- [x] Agent-as-Tool (as_tool)
- [x] CompoundTool (agent→execute→update)
- [x] HookRunner + ToolHook (lifecycle hooks)
- [x] Pipeline (sequential with error strategies)
- [x] Parallel (concurrent with merge + timeout)
- [x] Router (rule-based + LLM classifier)
- [x] RefinementLoop (iterative with convergence detection)
- [x] Test suite (193 tests)
- [x] Examples: 01-07 (tested with real LLMs)
- [x] MkDocs documentation site
- [ ] **Next: Phase 2 — Memory Architecture**
