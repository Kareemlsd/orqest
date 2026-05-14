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

> **Status note (2026-04-25):** This roadmap predates the v2 vision and the audit. Phases 2–5 below have all shipped. The five novel features that now drive Orqest's strategic direction are anchored in `.claude/VISION.md`; the current state is mapped against them in `.claude/AUDIT_2026-04-25.md`. The "Current Status" checklist at the bottom of this file is the authoritative status. Treat the headline phase markers as historical until this file is rewritten against the v2 phasing.

---

## Phase 2 — Memory Architecture ✅ SHIPPED (procedural memory deferred to Phase 2-extended)

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

## Phase 3 — Autonomy (Dynamic Agent Spawning) ✅ SHIPPED

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

## Phase 4 — Observability ✅ SHIPPED

**Goal:** When agent 4 in a pipeline produces bad output, trace the root cause.

- Lightweight `Span` and `Tracer` protocol (zero deps by default)
- Optional `orqest[otel]` for OpenTelemetry export
- In-process `EventBus` (subsumes HookRunner)
- Pipeline events flow through bus automatically

---

## Phase 5 — MCP Server (Claude Code Integration) ✅ SHIPPED

**Goal:** Claude Code builds agentic software using orqest as a tool.

- FastMCP server: `create_agent`, `run_agent`, `spawn_agent`, `list_agents`
- Run as: `python -m orqest.mcp.server`
- Dynamic Pydantic model construction from JSON Schema for `create_agent`

---

## Phase 6 — Resilience (now framed as **Self-healing primitives** per v2 vision)

**Goal:** Autonomous systems that detect and repair their own degradation.

- Watchdog: loop detection as history processor
- Diagnostic retry: error→diagnosis→enriched retry pattern
- Resource quotas enforcement
- Policy inheritance for spawned agents

> **Audit note (2026-04-25):** the audit confirms wide gaps here — `ToolHook` is observe-only, `resolve_model` has no fallback cascade, `MCPDiscovery → ToolRegistry` auto-wire is unbuilt, no watchdog primitives exist. **Blocked on Phase 7 (metacognition) — you can't recover from what you can't detect.**

---

## Phase 7 — Metacognition primitives (NEW — v2 vision feature #3)

**Goal:** Agents that report their own confidence and capability boundaries.

**Why this is the next move:** the audit identifies `BaseAgent.run` returning raw `OutputT` as the keystone gap. Without enriched output, `RefinementLoop` can't use agent self-evaluation (its evaluator already accepts a `BaseAgent`, latent), `SubAgentTool` can't expose confidence, `ContextManager` can't do salience-driven compaction, and `MetaOrchestrator` can't re-decompose on confidence drop. Highest distance from existing frameworks.

- `orqest.metacognition` module: `EnrichedOutput[T]` (output + confidence + uncertainty_targets + capability_boundary)
- `MetacognitionHook` — `ToolHook` that runs agent self-evaluation post-turn
- `BaseAgent.run_enriched(state) -> EnrichedOutput[T]` (additive)
- `RefinementLoop` `use_agent_confidence` flag — uses `EnrichedOutput.confidence` for convergence
- `SubAgentResult.confidence: float | None`
- `ToolHook` decision protocol upgrade (`HookDecision = Continue | Skip | Redirect | Abort`) — small interface change unlocking Phase 6 self-healing flows

---

## Phase 8 — Generative UI (NEW — v2 vision feature #5)

**Goal:** Agents emit UI component specs; the frontend hot-loads them.

- `UIComponentSpec[T]` Pydantic model + discriminator
- `ComponentRegistry` (server-side schema registry)
- Frontend resolver protocol (component-type → React component)
- Refactor `ExecutionPlan` to use the protocol (it's already the closest pattern in the codebase)
- Generic init+delta event shape on top of `AgentEvent`

---

## Phase 9 — Orchestration specs (closes runtime-agent-design loop)

**Goal:** LLM emits not just `AgentSpec` but `PipelineSpec`, `ParallelSpec`, `RouterSpec`, `RefinementLoopSpec`.

- Pydantic models for each orchestration primitive
- `from_json` hydrators in the autonomy `AgentFactory` (or a new `OrchestrationFactory`)
- LLM can design topology at runtime, not just agents

---

## Phase 2-extended — Procedural memory + production backend

**Goal:** Cognitive memory typology completeness.

- Add `Literal["semantic", "episodic", "procedural"]` to `MemoryEntry.memory_type`
- `Skill` / `Recipe` shape for procedural memory (tool-sequence-with-outcome)
- Per-kind retrieval strategies in `LocalMemoryStore` (semantic = vector, procedural = exact-match-on-trigger, episodic = time-windowed)
- Per-kind config in `MemoryConfig` (TTL for episodic, version-on-edit for procedural)
- Supabase pgvector backend

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
- [x] Test suite (655 tests as of 2026-05-02 — 360 baseline + 252 across the three Wave 1–3 ship days on 2026-04-25 + 43 from consumer-side polish 2026-04-26)
- [x] Examples: 01-07 (tested with real LLMs)
- [x] MkDocs documentation site
- [x] Memory subsystem (`MemoryStore` + `LocalMemoryStore`, semantic/episodic/**procedural**)
- [x] Autonomy (`AgentSpec`, `AgentFactory`, `ToolRegistry`, `MetaOrchestrator`)
- [x] Observability (`Span`, `Tracer`, `JSONTracer`, `EventBus`, `EventBusPublishHook`, `sse_sidecar`)
- [x] MCP client + server + **auto-discovery** (`ToolRegistry.get_or_discover`, `DiscoveryHook`, `PermissionGate`)
- [x] Polymath flagship demo (`demo/polymath/`)
- [x] **Wave 1: HookDecision + Metacognition + Procedural memory** (2026-04-25)
- [x] **Wave 2: Healing subsystem + MCP auto-wire** (2026-04-25)
- [x] **Wave 3: Generative UI** (2026-04-25)
- [x] **All five novel vision features ship as of 2026-04-25.**
- [x] Polymath consolidation onto `orqest.ui` + `orqest.healing` — shipped 2026-04-25 (ChartsTab/ReportTab absorbed into the dynamic dockview tab manifest; HealingRunner wired into Workbench)
- [x] Polymath cognitive surfacing (Cognitive Gutter, healing toasts, Memory tab, Agents tab) — shipped 2026-04-26
- [x] Polymath editorial redesign (claude.ai/design handoff: warm-neutral oklch + amber accent + Newsreader serif + Inter Tight grotesk) — shipped 2026-04-26
- [x] Concept pages for `metacognition`, `healing`, `generative_ui`, `autonomy`, `mcp` — shipped 2026-05-02
- [x] `orqest` skill folder for Claude Code (`.claude/skills/orqest/`) — shipped 2026-05-02
- [ ] Production memory backend (Supabase + pgvector) — purely additive; `MemoryStore` Protocol + `MemoryConfig` already accommodate it
- [ ] `ToolSandbox` for generated-code safety (Phase 3's deferred safety item) — relevant for agents that author + run their own tools
- [ ] PyPI release pipeline + version cuts (`0.1.0` and `0.2.0` cut in CHANGELOG; not yet published)
