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

## Phase 9 — Orchestration specs (closes runtime-agent-design loop) — ✅ shipped (2026-05-15)

**Goal:** LLM emits not just `AgentSpec` but `PipelineSpec`, `ParallelSpec`, `RouterSpec`, `RefinementLoopSpec`.

Shipped in `orqest/orchestration/spec.py` + `orqest/orchestration/hydrate.py`:

- Pydantic models for each orchestration primitive (plus `AgentStepSpec` / `FunctionStepSpec` atomic leaves), unified by `OperationSpec` (recursive) and `TopologySpec` (composite-only) discriminated unions.
- `topology_from_spec()` hydrator + `CallableRegistry` for explicit name→callable allowlists. **No `eval`, no `exec`** — security perimeter is "names from a user-controlled allowlist."
- `_TopologyAsStep` adapter so nested composites conform to the `Step` protocol.
- Closes the audit-named gap: LLM can now design topology at runtime, not just agents.

## Phase 10 — Topology evolution (ADAS-style search over Phase 9 IR) — ✅ shipped (2026-05-15)

**Goal:** Evolve agentic topology from real traces against a small gold set; the structural counterpart to GEPA's prompt evolution.

Shipped in `orqest/optimization/topology.py` + `orqest/optimization/meta_agent.py`:

- `TopologyGene` (encode/decode `TopologySpec` JSON; resilient fallback to seed on malformed reflection).
- `TopologyEvaluator` (subclass of `Evaluator`; surfaces `n_agents` / `depth` to `MetricBundle.raw`).
- `MetaAgentSearch` (ADAS-style design → reflexion → evaluate → archive loop), `Archive` with three pluggable strategies (`top_k` default per the [2510.06711 critique](https://arxiv.org/abs/2510.06711); `cumulative` ADAS-faithful; `parallel` for end-only selection).
- Two-phase recommended composition with GEPA (ADAS first, GEPA on the winner). Notebook 09 demonstrates the ablation.

Outstanding: per-step cost capture (today `cost_usd=0.0` for topology evaluations); `Pipeline.to_spec()` inverse direction; W3.C sandboxed codegen (raw Python `forward()` behind a `Sandbox` Protocol).

## Phase 11 — Runtime topology design — ✅ shipped (2026-05-15)

**Goal:** Close the loop between offline ADAS search (Phase 10) and the existing runtime agent design (`MetaOrchestrator`). Per-request topology synthesis with cache-amortized online learning over what works.

Shipped:

- `orqest/autonomy/runtime.py` — `RuntimeTopologyDesigner` (per-request synthesis via a user-provided `BaseAgent[GlobalState, TopologyDesign]`); `TopologyCache` Protocol with `NoCache` / `InMemoryLRU` / `MemoryStoreCache` implementations. Lives in `autonomy/` (not `optimization/`) because it's a runtime planner sibling to `MetaOrchestrator`, not an optimizer — there's no loss function or Pareto archive.
- `MemoryStoreCache` backed by `LocalMemoryStore` (`memory_type="semantic"`, `source_agent="topology_cache"` namespace) with reliability decay on failure — online learning for free via existing `PerKindConfig.decay_on_failure` machinery.
- `orqest/autonomy/topology_orchestrator.py` — `TopologyOrchestrator` parallel sibling to `MetaOrchestrator`. Returns `TopologyExecutionResult` with structural metrics, timing breakdown, cache_hit signal.
- Seed-library bootstrap: pass the Pareto front from offline `MetaAgentSearch` to the runtime designer as `seed_library=`; designer biases toward known-good shapes.
- 35 new tests (898 total), notebook 10 demonstrates end-to-end (cache reuse cuts design from ~3s to ~1ms; online-learning decay invalidates failed entries).

Outstanding (W3.D-G): `RetrievalPolicy` Protocol over the seed library (when libraries grow past ~20 entries), output-quality reliability signal (decay on bad outputs not just exceptions), `MetacognitionHook` integration (per-step confidence into `TopologyExecutionResult`), MCTS as alternative search-time engine feeding the same library.

## Phase 12 — Sandbox + dynamic tool spawning — ✅ shipped (2026-05-15)

**Goal:** Close the autonomy ladder's missing rung — when an LLM emits an `AgentSpec` requesting a brand-new capability, the framework materializes it safely instead of silently dropping the request. Pairs with the long-deferred Phase-3 `ToolSandbox` item.

Shipped:

- `orqest/sandbox/` — `Sandbox` Protocol + `ValidationError` + `ExecutionResult` + two backends. `InProcessSandbox` (Tier 0, refuses without `unsafe=True`); `SubprocessSandbox` (Tier 1 default, subprocess + RLIMIT_AS + RLIMIT_CPU + outer wait_for). Default-deny imports; defense-in-depth re-validation inside the subprocess.
- `orqest/autonomy/spec.py` — `GeneratedToolSpec` Pydantic model carrying `implementation: str`. `AgentSpec.tools` widened to smart-union of `ToolSpec | GeneratedToolSpec`.
- `orqest/autonomy/tool_factory.py` — `DynamicToolFactory.spawn(spec)` validates + produces a runnable `pydantic_ai.Tool`. Bus events for the full lifecycle.
- `orqest/autonomy/factory.py` — `AgentFactory(tool_factory=...)` dispatches mixed `ToolSpec` + `GeneratedToolSpec` lists; runtime async-bridge for spawn calls.
- `orqest/agents/base_agent.py` — `BaseAgent.add_tool(tool)` for runtime tool assignment to existing agents (invalidates the `_agent` cache; idempotent on name).
- 61 new tests (959 total). Notebook 11 demonstrates end-to-end with a real LLM successfully using a runtime-spawned `extract_dois` tool.

Closes the Phase-3 deferred `ToolSandbox` item from `.claude/ARCHITECTURE.md` §2.8. W3.C ADAS sandboxed codegen now unblocked. **W3.M shipped (Phase 13, see below).** Outstanding from this wave: W3.K (`SubprocessPoolSandbox` for amortized startup cost) and W3.L (`E2BSandbox` for hosted micro-VM).

## Phase 13 — Tier-2 Docker sandbox + per-user persisted MCP tool library — ✅ shipped (2026-05-16)

**Goal:** Hardened isolation tier for LLM-authored Python execution; runtime-spawned tools that survive across sessions for the same user. Closes W3.J (procedural-memory persistence for spawned tools) and W3.M (Docker / Firecracker isolation backends — Docker landed; Firecracker is the future Tier 3 seam).

Shipped:

- `orqest/sandbox/docker.py` — host-side `DockerSandbox` (Sandbox-Protocol-conformant; async context manager). Per-construction HMAC-secret mint; `docker run` with `--cap-drop=ALL --read-only --user 1000:1000 --pids-limit --memory --cpus`; MCP boot-wait poll via `/mcp` initialize; auto-discover host port from `NetworkSettings`. Required `user_id` + `session_id` ctor args.
- `orqest/sandbox/jwt.py` — minimal HS256 JWT (encode/decode/verify), constant-time signature compare, `alg=none` defended.
- `orqest/sandbox/_compat.py` — soft-import boundary for the optional `docker` SDK; friendly `ImportError` at first call.
- `orqest/sandbox/docker_runtime/` — IN-CONTAINER runtime package: FastMCP server (`server.py`), `SessionAuthMiddleware` (`auth.py`), per-agent `uv venv` + `uv pip install` allowlisted (`executor.py`), per-user SQLite `ToolStore` (`store.py`). Replays the persisted library on startup; threshold counter auto-promotes after N=3 invocations of the same `(name, code_hash)`; explicit `promote_tool` + `forget_tool` + `list_persisted_tools` MCP tools also exposed.
- `Dockerfile` (repo root) — `python:3.12-slim` + `tini` + `uv` + orqest + `fastmcp>=2.10,<2.14` (3.x changed middleware HTTP-context lifecycle in a way that breaks `get_http_headers()` for our auth path; pinned via `PIP_CONSTRAINT` so pydantic-ai's transitive `fastmcp>=3.2.4` doesn't override). Two build modes via `ARG ORQEST_SOURCE`: `pypi` (release) / `local` (dev).
- `orqest/workbench/workbench.py` — required `user_id` + `session_id` ctor args (BREAKING for any external Workbench() consumer; no external consumers exist as of 0.7.0). New `with_docker_sandbox(*, user_id, session_id, image, allowed_packages, ...)` lazy factory.
- `orqest/sandbox/protocol.py` — additive `agent_id` + `dependencies` kwargs on `Sandbox.execute`; Tier-0/1 accept-and-ignore.
- `orqest/mcp/{config,client}.py` — `MCPServerConfig.headers: dict[str, str]` and `transport: "streamable-http"` branch using `streamablehttp_client`.
- `orqest/memory/` — `memory_type="tool"` extension across `MemoryEntry` / `MemoryFilter`; `ToolStrategy` (exact-name match w/ FTS5 fallback) wired into `default_strategy_table`; `MemoryConfig.tool: PerKindConfig` (versioning enabled; no TTL).
- `orqest/autonomy/{spec,tool_factory,factory}.py` — `GeneratedToolSpec.dependencies: list[str]`; `agent_id` propagated through factory chain.
- ~74 new tests (1051 default + 13 marked `docker` = 1064 total). New `[tool.pytest.ini_options]` registers the `docker` marker.
- New optional dependency group `[dependency-groups] docker = ["docker>=7.0", "httpx>=0.27"]`.
- Honest threat model documented at `docs/concepts/sandbox.md` (Tier 0 → 1 → 2 → Tier 3 microvm seam): Tier 2 protects against accidental damage and most prompt-injection scenarios; not adversarial-multi-tenant grade — for that, run inside a microVM (Firecracker / Kata) or use a managed sandbox provider.

Outstanding (this wave): W3.K (`SubprocessPoolSandbox`), W3.L (`E2BSandbox`), Tier 3 `MicroVMSandbox` (Firecracker/Kata/gVisor) — all documented seams.

---

## Phase 2-extended — Procedural memory + production backend

**Goal:** Cognitive memory typology completeness.

- Add `Literal["semantic", "episodic", "procedural"]` to `MemoryEntry.memory_type`
- `Skill` / `Recipe` shape for procedural memory (tool-sequence-with-outcome)
- Per-kind retrieval strategies in `LocalMemoryStore` (semantic = vector, procedural = exact-match-on-trigger, episodic = time-windowed)
- Per-kind reliability policy in `MemoryConfig` / `PerKindConfig` (`decay_on_failure`, `prune_below`)
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
- [x] Test suite (689 tests as of 2026-05-14 — 655 baseline → 664 after the `[0.3.0]` reconcile pass → 670 after the `[0.4.0]` advance pass → 689 with the unreleased reasoning/thinking feature)
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
