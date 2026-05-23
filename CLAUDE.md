# Orqest — Agent Instructions

## What This Is

Orqest is a Python framework for building autonomous agentic AI systems on top of pydantic-ai. It ships typed agent primitives, orchestration patterns, lifecycle hooks, session persistence, agent composition, memory, dynamic agent spawning, MCP client + server, and first-class observability.

**Design principle:** *"Core Orqest manages the shape and flow of intelligence; Extensions manage the matter and action of the domain."*

**Domain-agnostic litmus test:** "Can a developer building a headless coding assistant use this feature without knowing what any particular consuming app does?" If no, the feature belongs in the consumer, not in Orqest.

**Current version:** `0.8.0` (`pyproject.toml`). **All five novel vision features shipped (2026-04-25)** — runtime agent design, cognitive memory typology (semantic / episodic / procedural), metacognition primitives, self-healing primitives, generative UI. **Phase 13 (2026-05-16)** added the Tier-2 Docker sandbox (`DockerSandbox`) + per-user persisted MCP tool library — the published `orqest/agent-runtime` image runs an in-container FastMCP server with HMAC-JWT auth (scope-separated: `agent` for code execution, `operator` for persistence), per-agent `uv` venvs, and SQLite-backed cross-session tool persistence per user. **Phase 13 hardening pass (2026-05-23, [#8](https://github.com/Kareemlsd/orqest/pull/8))** closed five safety gaps: widened the static validator to block reflection helpers (`getattr` / `setattr` / `type` / `dir` / `super`) and string-keyed dunder subscripts; restricted `__builtins__` in every subprocess wrapper via shared `_safe_builtins.py`; rejected path-traversal in `user_id` / `session_id` / `agent_id` via `_identifiers.py`; introduced JWT scope separation so `promote_tool` / `forget_tool` reject agent-scope tokens; flipped `ORQEST_ALLOWED_ORIGINS` default to localhost-only.

## Project Structure

```
orqest/
├── __init__.py              # Root re-exports (see "Public API" below)
├── config.py                # OrqestConfig (frozen dataclass) + load_config() + get_default_config()
├── hooks.py                 # HookRunner + ToolHook protocol + HookDecision (Continue/Skip/Redirect/Abort)
│
├── agents/                  # Agent primitives
│   ├── base_agent.py        # BaseAgent[StateT, OutputT], call_model / call_model_stream / stream_output / stream_events
│   ├── state.py             # GlobalState (dual-layer: app messages + pydantic-ai message_history)
│   ├── session_state.py     # BaseSessionState (serializable via SerializableMessageHistory annotation)
│   ├── compound_tool.py     # CompoundTool (agent → execute → update, with hook dispatch)
│   ├── context_manager.py   # ContextManager (summarize at 60%, truncate at 85%)
│   ├── retry.py             # run_with_retry() + default enrichment
│   └── tool_wrapper.py      # as_tool() — wrap a BaseAgent as a pydantic-ai Tool
│
├── orchestration/           # Composition primitives
│   ├── types.py             # ErrorStrategy, StepConfig, PipelineEvent
│   ├── step.py              # Step protocol, AgentStep, FunctionStep, StepLike auto-coercion
│   ├── pipeline.py          # Pipeline (sequential, STOP/SKIP/RETRY)
│   ├── parallel.py          # Parallel (concurrent + merge + timeout)
│   ├── router.py            # Router (rule-based + LLM classifier, with fallback)
│   ├── loop.py              # RefinementLoop (evaluator + convergence detection)
│   ├── spec.py              # PipelineSpec/ParallelSpec/RouterSpec/RefinementLoopSpec + AgentStepSpec/FunctionStepSpec — Pydantic IR
│   └── hydrate.py           # CallableRegistry + topology_from_spec() — IR → live runtime
│
├── memory/                  # Cognitive memory typology (semantic / episodic / procedural)
│   ├── store.py             # MemoryStore protocol, MemoryEntry, MemoryFilter, Skill / ToolCallSpec / SkillExample
│   ├── local.py             # LocalMemoryStore (SQLite + FTS5; strategy-dispatch for per-kind retrieval)
│   ├── strategies.py        # SemanticStrategy, EpisodicStrategy, ProceduralStrategy (+ injected fuzzy judge)
│   └── config.py            # MemoryConfig + PerKindConfig (per-kind decay / prune policy)
│
├── autonomy/                # Runtime planners + dynamic tool spawning (Phases 3, 11, 12)
│   ├── spec.py              # AgentSpec, ToolSpec, GeneratedToolSpec (serializable contracts; mixed via smart-union)
│   ├── factory.py           # AgentFactory → DynamicAgent; dispatches ToolSpec → registry, GeneratedToolSpec → tool_factory
│   ├── registry.py          # ToolRegistry (register / get / search / list_all)
│   ├── tool_factory.py      # DynamicToolFactory (GeneratedToolSpec → pydantic_ai.Tool via Sandbox)
│   ├── meta.py              # MetaOrchestrator (goal → flat decomposition → spawn → execute)
│   ├── runtime.py           # RuntimeTopologyDesigner + TopologyCache (NoCache/InMemoryLRU/MemoryStoreCache) — per-request topology synthesis with cache
│   └── topology_orchestrator.py  # TopologyOrchestrator (goal → topology design → hydrate → run → record)
│
├── sandbox/                 # Phases 12 + 13 — safe execution surface for LLM-generated Python
│   ├── protocol.py          # Sandbox Protocol + ValidationError + ExecutionResult; execute() takes optional agent_id + dependencies
│   ├── _static.py           # AST validator shared by all backends (default-deny imports + forbidden-names check incl. reflection helpers + Subscript guard)
│   ├── _safe_builtins.py    # Curated __builtins__ + restricted __import__ shared by every tier (Phase-1 hardening — load-bearing)
│   ├── _identifiers.py      # Strict identifier grammar for user / session / agent IDs — path-traversal guard
│   ├── inprocess.py         # InProcessSandbox (Tier 0 — requires unsafe=True; exec() in restricted namespace via _safe_builtins)
│   ├── subprocess.py        # SubprocessSandbox (Tier 1 default — subprocess + RLIMIT_AS + RLIMIT_CPU + outer wait_for; wrapper loads helpers by file path)
│   ├── docker.py            # DockerSandbox (Tier 2 — per-session container; needs `docker` dep group + orqest/agent-runtime image). mint_operator_token() for host persistence calls.
│   ├── jwt.py               # Minimal HS256 JWT (encode/decode/verify, constant-time compare; `scope` claim carried verbatim)
│   ├── _compat.py           # Soft-import boundary for the `docker` SDK (friendly ImportError when missing)
│   └── docker_runtime/      # Phase 13 — IN-CONTAINER runtime package (runs INSIDE orqest/agent-runtime)
│       ├── __main__.py      # Entry point — reads ORQEST_USER_ID/SESSION_ID/HMAC_SECRET, boots FastMCP on 0.0.0.0:8000
│       ├── server.py        # build_server[_from_env]() — FastMCP w/ 4 built-in tools + persisted-library replay; promotion threshold check under asyncio.Lock
│       ├── auth.py          # SessionAuthMiddleware — JWT validation + scope enforcement (DEFAULT_OPERATOR_TOOLS = {promote_tool, forget_tool}) + Origin allowlist (default localhost)
│       ├── store.py         # ToolStore — per-user SQLite (name, version) PK + dedup by implementation_hash
│       └── executor.py      # Per-agent uv venv (--system-site-packages so wrapper can load _safe_builtins/_static) + uv pip install (allowlisted) + RLIMIT-bounded subprocess; ensure_venv/install_deps under per-agent lock
│
├── observability/           # Phase 4 — shipped
│   ├── tracer.py            # Span, Tracer protocol, JSONTracer (in-memory, JSON export)
│   ├── events.py            # AgentEvent, EventBus (pub/sub, fire-and-forget)
│   ├── event_bus_hook.py    # EventBusPublishHook (ToolHook → EventBus bridge)
│   └── sse_sidecar.py       # sse_sidecar() — SSE stream w/ replay + heartbeat + ring buffer
│
├── workbench/               # Runtime container (bundles memory + tracer + bus + recent-events buffer + ui_registry)
│   └── workbench.py         # Workbench, reset(), snapshot()
│
├── compound/                # New-style compound tool (Phase 1c)
│   └── sub_agent_tool.py    # SubAgentTool[StateT, ResultT] + SubAgentResult
│                            # Captures agent → executor → state-update → optional refinement
│
├── plan/                    # Typed multi-step workflow tracking
│   └── execution_plan.py    # ExecutionPlan, PlanTask, PlanSubtask, PlanStatus
│                            # to_sse_init() is byte-stable (frontend contract)
│
├── mcp/                     # Phase 5 — shipped + auto-discovery
│   ├── config.py            # MCPServerConfig, MCPConfig
│   ├── client.py            # MCPConnection, MCPServerManager (multi-server lifecycle)
│   ├── adapter.py           # MCPToolAdapter — MCP tool defs → pydantic-ai Tool instances
│   ├── discovery.py         # MCPDiscovery, DiscoveredServer (registry + well-known search)
│   ├── discovery_hook.py    # DiscoveryHook (ToolHook → opportunistic auto-register on tool-not-found)
│   ├── permission.py        # PermissionGate Protocol + AllowAll / DenyAll / AllowList (default DenyAll)
│   └── server.py            # create_orqest_server() — expose Orqest as FastMCP
│
├── metacognition/           # Vision feature #3 — confidence-aware output (Wave 1.3)
│   ├── enriched.py          # EnrichedOutput[OutputT] (output + confidence + uncertainty + capability_boundary)
│   ├── protocol.py          # ConfidenceProtocol + StructuredOutput / LLMSelfRating / Ensemble
│   ├── hook.py              # MetacognitionHook (ToolHook → metacognition.confidence events)
│   ├── salience.py          # confidence_salience / recency_salience for ContextManager
│   └── config.py            # MetacognitionConfig (redecompose_threshold, max_redecompositions)
│
├── healing/                 # Vision feature #4 — self-healing (Wave 2)
│   ├── watchdog.py          # Watchdog Protocol + Detection
│   ├── stall.py             # StallDetector (timeout on open tool calls)
│   ├── loop.py              # LoopDetector (sliding window of (tool, args_hash))
│   ├── regression.py        # RegressionDetector (subscribes to metacognition.confidence)
│   ├── recovery.py          # RecoveryAction union + WatchdogHook + default_policy
│   ├── fallback.py          # FallbackModel (subclass of pydantic_ai.Model) + resolve_model_with_fallback
│   ├── runner.py            # HealingRunner (subscribes watchdogs, runs poll loop)
│   └── config.py            # HealingConfig (frozen dataclass)
│
├── ui/                      # Vision feature #5 — generative UI (Wave 3)
│   ├── spec.py              # UIComponentSpec[T] generic + UIDeltaEvent (replace/merge/append/remove)
│   ├── registry.py          # ComponentRegistry per-Workbench + default_registry()
│   ├── emitter.py           # UIEmitter — init/delta/remove convenience over EventBus
│   ├── events.py            # ui_init/delta/remove_event_type() helpers
│   └── components/          # First-party: 17 components in 3 layers (see default_registry())
│
├── tools/                   # First-party reusable pydantic-ai Tools
│   └── web.py               # web_search, web_fetch + result models (tavily/exa/brave/serper)
│
├── optimization/            # Reflective evolution — search-time only (W1: prompts via GEPA, W3: topology via MetaAgentSearch)
│   ├── _compat.py           # Single-file gepa import boundary (friendly ImportError when missing)
│   ├── config.py            # OptimizationConfig (frozen dataclass, FrontierType Literal)
│   ├── bundle.py            # MetricBundle + MetricWeights (5 dimensions + raw extension)
│   ├── genome.py            # PromptGene / ScalarGene / CategoricalGene + Genome
│   ├── evaluator.py         # Evaluator + GoldExample (single-agent path)
│   ├── adapter.py           # OrqestGEPAAdapter + OrqestEvalBatch (GEPA Protocol bridge)
│   ├── runner.py            # OptimizationRunner + OptimizationResult (drives gepa.optimize)
│   ├── apply.py             # apply_result + OptimizationDiff (dry-run by default; resets _agent cache)
│   ├── topology.py          # TopologyGene + TopologyEvaluator + unpack_topology_output (W3.A/B)
│   └── meta_agent.py        # MetaAgentConfig + Archive + MetaAgentSearch (W3 — search-time ADAS loop)
│
├── utils/
│   ├── llm_model.py         # resolve_model() — lazy registry (OpenAI, Anthropic, Google, OpenRouter)
│   └── token_counter.py     # estimate_tokens() (heuristic 3.5 chars/token)
│
└── io_utils/
    └── load_sys_prompt.py   # load_sys_prompt() — upward search for system_prompts/ dir
```

### Public API (root re-exports from `orqest/__init__.py`)

`OrqestConfig`, `load_config`, `get_default_config`, `HookRunner`, `ToolHook`, `HookDecision` (`Continue` / `Skip` / `Redirect` / `Abort`), `HookAbortError`, `Pipeline`, `Parallel`, `Router`, `RefinementLoop`, `ExecutionPlan`, `PlanStatus`, `PlanSubtask`, `PlanTask`, `Workbench`, `EnrichedOutput`, `MetacognitionConfig`, `HealingConfig`, `OptimizationConfig`, `MetaAgentConfig`.

Other subsystems are imported via their submodules (`from orqest.memory import LocalMemoryStore, Skill`, `from orqest.observability import EventBus, sse_sidecar`, `from orqest.compound import SubAgentTool`, `from orqest.metacognition import StructuredOutputProtocol, MetacognitionHook`, `from orqest.healing import HealingRunner, StallDetector, FallbackModel`, `from orqest.ui import UIComponentSpec, ChartComponent, UIEmitter`, etc.) so the root namespace stays small.

### Tests

Mirrors source layout under `tests/`. As of latest collect: **1117 tests** — 1104 in the default suite + 13 marked `docker` (require a Docker daemon AND the `orqest/agent-runtime` image, skipped by default). The Phase-13 wave added ~74 tests across the new `tests/sandbox/test_jwt.py`, `tests/sandbox/test_docker_compat.py`, `tests/sandbox/test_docker.py`, `tests/sandbox/docker_runtime/`, `tests/mcp/test_streamable_http_transport.py`, `tests/memory/test_tool_memory_type.py`, `tests/autonomy/test_generated_tool_spec_dependencies.py`, `tests/workbench/test_user_session.py`. History: 655 baseline → 664 (`[0.3.0]`) → 670 (`[0.4.0]`) → 689 (reasoning) → 768 (GEPA `optimization`) → 863 (W3 topology evolution) → 898 (runtime topology) → 959 (Phase 12 sandbox + dynamic tool spawning) → 1064 (Phase 13 Docker tier + per-user persisted MCP tool library) → **1117 (post-Phase-13 hardening: orphan-tool-return repair, schema-validation guard, benchmarks fixture, sandbox helpers, multi-trial evaluation)**. Coverage spans agents, orchestration (incl. spec/hydrate IR), memory, mcp, autonomy, observability, workbench, compound, plan, tools, utils, io_utils, **metacognition, healing, ui, optimization (incl. topology + meta_agent), sandbox (incl. docker_runtime)**, plus root-level tests for config, hooks, hook_decision, budget_tool_results, context_manager.

### Notebooks + concept docs are the entry surface

The `notebooks/` tour (12 narrative notebooks) is the empirical dogfooding pass — each composes multiple primitives end-to-end against a real LLM. The `docs/concepts/*.md` pages are the one-primitive-at-a-time reference, each with a runnable snippet. There is no separate `examples/` folder; that level of detail lives in the concept docs.

## Key Conventions

- **Async-first.** Every agent-touching path is `async def`.
- **Pydantic everywhere.** State, output, memory entries, plan tasks — all Pydantic `BaseModel`. Config uses frozen dataclass (pattern: runtime immutability without Pydantic validation overhead).
- **Generic typing.** `BaseAgent[StateT, OutputT]`, `SubAgentTool[StateT, ResultT]`, `Pipeline[InputT, OutputT]`, etc. — always specify type parameters.
- **Explicit dependencies.** No import-time side effects. Functions take deps as arguments.
- **Model format.** `LLM_MODEL=provider:model_id` (e.g., `openai:gpt-4.1`, `anthropic:claude-sonnet-4-6`). `resolve_model()` dispatches to lazy-imported providers.
- **Fire-and-forget hooks.** `HookRunner` wraps hook invocations in `try/except`, logs at WARNING; hook failure never breaks tool execution.
- **Best-effort memory.** `LocalMemoryStore` swallows SQLite errors and logs — memory subsystem cannot block an agent.
- **Build on pydantic-ai.** We wrap, compose, and bridge — we do not re-implement. Models, Tools, ModelMessages are all pydantic-ai native types.
- **Python 3.12+.** Modern typing (`type X = ...`, generic `class Foo[T]:`) used throughout.
- **Testing.** pytest + pytest-asyncio. Mock the model layer; never require real API keys for the CI-blocking suite.
- **Package docs live at `docs/`** (MkDocs Material + mkdocstrings). Every battery gets a concept doc under `docs/concepts/<name>.md` and an API reference entry wired via mkdocstrings.
- **Every battery ships with a benchmark.** Convention established in `[0.9.0]`: when a new battery (or a meaningful composition of batteries) lands, it ships with a reproducible head-to-head in `benchmarks/<name>/` that measures its delta over a sensible baseline. The benchmark folder contains: `run.py` (the entry point), a `README.md` documenting expected numbers + variance + cost, and any problem-fixture modules. Multi-trial averaging is the default (single-LLM-run variance swings ±10pp; one trial misleads). The benchmark is the contract: if the numbers regress, the battery regressed — and consumers can verify the win claim with one shell command. Notebook 12 (`notebooks/12_combo_autonomous_coder.ipynb`) walks the architecture; `benchmarks/coding/` is the canonical reference for the layout. *Don't ship a new battery without one.* See `benchmarks/README.md`.

## Dev Commands

```bash
# Install in editable mode (local venv)
uv pip install -e .

# Run full suite (1051 tests; +13 marked `docker` skip without daemon)
.venv/bin/python -m pytest tests/ -v

# Single file / test-by-name
.venv/bin/python -m pytest tests/agents/test_base_agent.py -v
.venv/bin/python -m pytest tests/ -k "test_refinement_loop_converges" -v

# Lint + format
ruff check orqest/
ruff check orqest/ --fix
ruff format orqest/

# Docs
uv run mkdocs serve        # local with hot reload
uv run mkdocs build        # static site → site/

# Package build
python -m build
```

## What Exists Today

### Phase 1 — Composition Primitives ✅

**Agents / State / History**
- `BaseAgent[StateT, OutputT]` with async `call_model`, `call_model_stream`, `stream_output`, `stream_events`
- `GlobalState` — dual layer: app-level message dicts (for persistence) + pydantic-ai `ModelMessage` list (for next run)
- `BaseSessionState` — adds `session_id`, `created_at`, `SerializableMessageHistory` annotation so ModelMessages serialize cleanly
- History processors: `keep_recent_messages`, `budget_tool_results`, `ContextManager.compact()` — all pure functions, composable
- `ContextManager` — token-aware three-tier compaction (tool-result snip → turn summarization at 60% → emergency truncation at 85%)
- `as_tool()` — wrap any `BaseAgent` as a pydantic-ai Tool (stateless per invocation)
- `CompoundTool` — agent → execute → state update with HookRunner dispatch
- `run_with_retry()` — exception-based retry with default enrichment (distinct from `SubAgentTool`'s quality-refinement)
- `resolve_model()` — lazy registry (OpenAI, Anthropic, Google, OpenRouter); the full `pydantic-ai` dependency bundles every provider SDK, so the lazy import is defensive, not a cost-saving mechanism

**Orchestration**
- `Pipeline[InputT, OutputT]` — sequential with per-step `ErrorStrategy` (STOP / SKIP / RETRY)
- `Parallel[OutputT]` — concurrent via `asyncio.gather` with `MergeStrategy.collect_all` / `first_wins` (extensible via callable)
- `Router[InputT, OutputT]` — `Route(condition=...)` rules or `classifier: BaseAgent | async callable`, with fallback
- `RefinementLoop[StateT, OutputT]` — evaluator-driven iteration, `EvalResult`, `IterationRecord`, `LoopResult(exit_reason="passed"|"max_iterations"|"timeout"|"converged")`
- `Step` protocol + `AgentStep` / `FunctionStep` + `_coerce_step()` auto-coercion of `StepLike = Step | BaseAgent | callable`

**Hooks**
- `HookRunner` + `ToolHook` (`before_tool`, `after_tool`, `on_error`) — partial implementations allowed (hasattr check); methods may return `None` (legacy fire-and-forget) or :class:`HookDecision`. `HookRunner` aggregates decisions first-non-Continue-wins; `Abort` short-circuits with `HookAbortError`.
- `HookDecision` discriminated union: `Continue` / `Skip(reason, stub_result)` / `Redirect(new_args, new_tool, reason)` / `Abort(reason)`. Honored by `CompoundTool`, `run_with_retry`, `MetaOrchestrator._execute_subtask`. *Note:* hooks fire only at compound-flow boundaries — they do NOT intercept pydantic-AI's internal tool dispatch.

### Phase 2 — Memory ✅ (semantic + episodic + procedural)

- `MemoryStore` protocol (`store`, `recall`, `forget`, `update_reliability`, `count`).
- `MemoryEntry` — `content`, `structured_content`, `memory_type` (`"semantic" | "episodic" | "procedural"`), `source_agent`, `confidence`, `embedding`, `metadata`, `created_at`, `last_accessed`, `access_count`, `reliability_score`.
- `Skill` / `ToolCallSpec` / `SkillExample` — Pydantic shapes for procedural memory content (tool-sequence-with-outcome). Validation gated to `memory_type == "procedural"`.
- `MemoryFilter` — query constraints + `skill_name` / `skill_min_version` for procedural filtering.
- `LocalMemoryStore` — SQLite + FTS5 (with LIKE fallback), lazy init, errors swallowed. Recall dispatches to a per-kind :class:`RetrievalStrategy` (Semantic / Episodic / Procedural). Also exposes `list_recent(*, memory_type=None, limit=50)` — browse-style enumeration newest-first — and `prune_expired()` — best-effort TTL maintenance. Optional `embedder` param: when set, `store()` embeds content and semantic recall ranks by cosine similarity (else FTS5/LIKE).
- `ProceduralStrategy` — exact-match on `structured_content.trigger` (case-insensitive substring); optional injected `fuzzy_judge` callable for near-miss queries.
- `MemoryConfig` + `PerKindConfig` — frozen dataclass. `PerKindConfig` carries the per-kind policy: `decay_on_failure` / `prune_below` (read by `update_reliability`), `ttl_days` (read by `prune_expired`), `version_on_edit` (read by `store` — bumps a procedural skill's `version` and keeps prior rows). `backend` / `supabase_*` are preview seams for a future pgvector backend.

### Phase 3 — Autonomy ✅

- `AgentSpec` / `ToolSpec` — serializable contracts. LLM can emit these as structured output.
- `AgentFactory.spawn(spec) -> DynamicAgent` — builds a Pydantic output model from JSON Schema via `pydantic.create_model()`; resolves tools from the registry; injects constraints into the system prompt.
- `ToolRegistry` — `register`, `get`, `search(query, k)` (keyword scoring), `list_all`, `remove`, dunder methods.
- `MetaOrchestrator(planner_agent, registry, default_model, *, bus: EventBus | None = None)` — goal → `TaskDecomposition` → per `SubTask` spawn-or-find agent → execute → `SubTaskResult` → aggregated `ExecutionResult`. Optional `bus` parameter (added 2026-04-26) wires the orchestrator to an `EventBus`; when low-confidence triggers re-decomposition it emits a typed `metacognition.redecomposition_triggered` event with `{subtask_name, confidence, threshold, attempt, max_attempts, remaining_subtasks}`.
- `DynamicAgent` extends `BaseAgent[GlobalState, BaseModel]`.

### Phase 4 — Observability ✅

- `Span` — `trace_id`, `span_id`, `parent_span_id`, `name`, `agent_name`, timing, `status`, `attributes`, `events`.
- `Tracer` protocol; `JSONTracer` is the default in-memory implementation (no external deps).
- `AgentEvent` — frozen immutable event (`event_type`, `agent_name`, `timestamp`, `data`, `span_id`, `trace_id`).
- `EventBus` — in-process pub/sub. `subscribe(event_type)`, `subscribe_all`, `emit(event)`. Handler exceptions logged and discarded.
- `EventBusPublishHook` — bridges `ToolHook` → `EventBus`; emits `tool.before`, `tool.after`, `tool.error` with configurable preview truncation.
- `sse_sidecar(bus, replay=(), heartbeat_s=15.0, queue_size=256)` — AsyncIterator yielding SSE-formatted strings; ring-buffered against slow consumers; optional historical replay for reconnection.

### Phase 5 — MCP (Client + Server + Auto-wire) ✅

- `MCPServerConfig` / `MCPConfig` — explicit server definitions + auto-discovery toggle.
- `MCPConnection(config)` — single server lifecycle: `await connect()` → `.tools` → `await disconnect()`.
- `MCPServerManager` — multi-server orchestration, `async with` context manager, `connect_all`, `get_all_tools` (flat list), `search_tools`.
- `MCPToolAdapter.adapt[_many]` — MCP tool definitions → pydantic-ai `Tool` instances. Wraps callers in graceful error-string return.
- `MCPDiscovery.search(query, max_results)` — probes any configured `well_known_urls` for `/.well-known/mcp.json`, then queries the registry endpoints; dedups by name. Returns `DiscoveredServer` records. **Preview** — registry response-shape parsing is untested against live registries; no web-search fallback.
- Auto-discovery scans `~/.claude.json`, `~/.claude/claude.json`, `~/.config/Claude/claude_desktop_config.json`.
- `create_orqest_server(factory, registry, meta, default_model, api_key)` — FastMCP server exposing `create_agent`, `run_agent`, `solve_goal`, `list_agents`. Run with `python -m orqest.mcp.server`.
- **Auto-wire (2026-04-25):** `ToolRegistry.get_or_discover` (deliberate path) + `DiscoveryHook` (opportunistic recovery from "tool not found" errors) + `PermissionGate` (`AllowAll` / `DenyAll` / `AllowList` regex; default `DenyAll` — discovery is opt-in). Audit-log emission via `discovery.requested` / `discovery.connected` / `discovery.denied` / `discovery.failed` events.

### Phase 6 — Self-healing primitives ✅ (vision feature #4)

- `Watchdog` Protocol + `Detection` Pydantic model. Detectors observe; the policy decides recovery; `WatchdogHook` translates intent into a `HookDecision`.
- `StallDetector` — flags open tool calls exceeding `timeout_s`; idempotent subscribe; suppresses double-fire on same call.
- `LoopDetector` — sliding window of `(tool_name, args_hash)` pairs; fires when count > `threshold_k`; suppression resets when pair changes.
- `RegressionDetector` — sliding window of `metacognition.confidence` events; fires on head-half-mean − tail-half-mean ≥ `drop_threshold`. Silently no-ops when no metacog events flow (graceful degradation).
- `RecoveryAction` discriminated union: `EscalateToUser` / `AbortRun` — both produce a real `HookDecision` (`Skip` / `Abort`). `default_policy` → `AbortRun` for every detector; consumers override via custom callable. The union is **deliberately lean** — model-level recovery is `FallbackModel`, tool-level recovery is `DiscoveryHook`; both are dedicated, composable mechanisms rather than `RecoveryAction` variants.
- `WatchdogHook(watchdogs, *, policy, bus)` — `ToolHook` whose `before_tool` consults watchdogs and returns a `HookDecision`. Emits `healing.action` events when bus is configured.
- `FallbackModel` — subclasses `pydantic_ai.models.Model`. Sticky failover; transient classifier (5xx / timeout / rate-limit → fall back; auth / validation → propagate). Emits `healing.model_fallback` on chain advance, **and `healing.model_chain_exhausted`** (added 2026-04-26) with `{models_tried, last_error_type, last_error}` immediately before raising `RuntimeError` when the chain is fully spent.
- `resolve_model_with_fallback(models, *, api_key, bus, transient_predicate)` — accepts a chain; skips per-provider keys missing from `dict[provider, key]` map; raises `ValueError` if no entry resolves.
- `HealingRunner` async context manager — subscribes watchdogs to a bus, runs poll loop emitting `healing.detection`, owns the `WatchdogHook` and the (optional) `FallbackModel`. Poll loop swallows watchdog crashes.
- `Workbench.with_healing(config, *, api_key=...)` — convenience factory; lazy-imports `orqest.healing` so workbench stays import-light.
- `HealingConfig` — frozen dataclass: `stall_timeout_s`, `loop_threshold_k`/`window_n`, `regression_window_n`/`drop_threshold`, `poll_interval_s`, `fallback_models`, `enable_*` flags.

### Phase 7 — Metacognition primitives ✅ (vision feature #3)

- `EnrichedOutput[OutputT]` — `output` + `confidence: float | None` (in `[0, 1]`) + `uncertainty_targets: list[str]` + `capability_boundary: bool` + `protocol_name` + `metadata`.
- `ConfidenceProtocol` — pluggable strategy. Three concrete:
  - `StructuredOutputProtocol` — zero extra cost; lifts `self_confidence`/`uncertain_about`/`outside_my_capability` fields off the agent's own `OutputT` (duck-typed; field names overridable). **Default recommended.**
  - `LLMSelfRatingProtocol` — +1 LLM call; rater agent emits a JSON rating; markdown-fence-tolerant parser.
  - `EnsembleProtocol(k=N)` — +k–1 parallel calls; confidence = pairwise agreement (`_default_agreement` over `model_dump`).
- `MetacognitionHook` — `ToolHook` that emits `metacognition.confidence` events when a tool result is an `EnrichedOutput`. Returns `None` (auto-wraps to `Continue`).
- `BaseAgent.run_enriched(state, *, confidence_protocol=None)` — additive method (`run` untouched). Returns `EnrichedOutput`; protocol failures surface as `confidence=None` with `metadata["protocol_error"]`.
- `BaseAgent` ctor gains keyword-only `confidence_protocol` for an agent-level default.
- `RefinementLoop` ctor gains `confidence_threshold: float | None` (exit reason `"confident"` when score ≥ threshold) and `agent_self_eval: BaseAgent | None` (mutually-exclusive scoring path: synthesises `EvalResult(passed=False, score=enriched.confidence)`). `agent_self_eval` requires the agent to carry a `confidence_protocol` — validated at construction.
- `SubAgentResult.confidence` / `uncertainty_targets` / `capability_boundary` (additive optional fields). `SubAgentTool.run(use_enriched=True)` lifts the final-iteration enrichment onto the result.
- `ContextManager(salience_fn=...)` — pluggable per-message salience scorer; emergency truncation rescues high-salience old messages on top of the recency window. `confidence_salience` / `recency_salience` ship in `orqest.metacognition.salience`.
- `MetaOrchestrator(metacognition: MetacognitionConfig | None = None)` — re-decomposes remaining subtasks when `_extract_confidence(result.output) < redecompose_threshold`, bounded by `max_redecompositions`. The `_extract_confidence` helper reads `EnrichedOutput.confidence`, then `output.confidence`, then `output.metadata["confidence"]` — picking up the latent shape `_find_or_spawn` already prompts spawned agents to emit.

### Phase 8 — Generative UI ✅ (vision feature #5)

- `UIComponentSpec[T]` — generic Pydantic with `component_type` `Literal` discriminator + `component_id` + typed `data: T` + `metadata` + `created_at`. Open extension point: third parties register their own component classes.
- `UIDeltaEvent` — partial update with `op: Literal["replace","merge","append","remove"]` + dot-path + value.
- `ComponentRegistry` — per-Workbench (not module-level singleton): `register`, `get`, `list_types`, `validate_payload`. `default_registry()` returns a registry pre-loaded with first-party components.
- `UIEmitter(bus)` — convenience facade for `init` / `delta` / `remove` events on the bus. Bus failures emit DEBUG log; never raise.
- SSE event-type conventions: `ui.<component_type>.{init,delta,remove}`. Helpers `ui_init_event_type` / `ui_delta_event_type` / `ui_remove_event_type` keep consumers decoupled from string literals.
- First-party components — 17 total, wired via `default_registry()`: `PlanComponent`, `ChartComponent`, `TableComponent`, `FormComponent`, `TakeoverDialogComponent`, plus Layer-1 compositional primitives (`Layout`, `Text`, `Markdown`, `Image`, `Badge`, `Button`, `Input`), Layer-2 declarative grammars (`VegaChart`, `Mermaid`, `Latex`, `JsonViewer`), and a Layer-3 `SandboxedHTML` escape hatch.
- `ExecutionPlan.enable_ui_events(*, component_id="plan")` — opt-in flag-gated dual emission of `ui.plan.init` / `ui.plan.delta` alongside legacy `plan.init` / `plan.task.updated`. Default off so existing emission-count assertions stay byte-identical. `ExecutionPlan.as_component()` wraps the plan as a `PlanComponent`.
- `Workbench(ui_registry=..., auto_register_first_party_ui=True)` — ctor kwargs; default constructs `default_registry()`.

### Cross-battery integration points

- `Workbench` bundles `memory + tracer + event_bus + recent_events buffer + ui_registry` for one container you pass around instead of plumbing the pieces.
- `ExecutionPlan.set_task_status(task_id, status, *, bus=...)` — pass the Workbench's bus to surface plan updates to the SSE sidecar. Call `enable_ui_events()` to also emit typed `ui.plan.delta` events.
- `EventBusPublishHook` goes into `HookRunner` so every `CompoundTool` / `SubAgentTool` run emits `tool.before/after/error` without rewiring consumers.
- `MetacognitionHook` rides alongside `EventBusPublishHook` — emits `metacognition.confidence` whenever a tool returns an `EnrichedOutput`. `RegressionDetector` (healing) subscribes to those events. **Cross-feature handshake: metacognition produces the signal; healing acts on it.**
- `MCPServerManager.get_all_tools()` can seed a `ToolRegistry`. `ToolRegistry.get_or_discover` extends this with auto-discovery on miss, gated by `PermissionGate` (default `DenyAll`).
- `WatchdogHook` returns `HookDecision` directives that flow through the same `HookRunner` aggregation as security/policy hooks. `default_policy` maps every Detection to `AbortRun`; consumers override.
- `FallbackModel` subclasses `pydantic_ai.models.Model`, so it slots directly into `BaseAgent(model=...)` without changes to the Agent loop.
- `Workbench.with_healing(config, *, api_key=...)` — one-liner factory that wires watchdogs to the workbench's bus and returns a `HealingRunner` ready as an async context manager.
- `SubAgentTool` handles *quality*-based refinement (evaluator → `build_refinement_prompt` → rerun). `run_with_retry` handles *exception*-based retry. `RefinementLoop(confidence_threshold=…, agent_self_eval=…)` adds *confidence*-based exit. All three stack.

### Web tools

- `orqest.tools.web_search(query, k, provider, api_key, timeout_s)` — provider from arg → `ORQEST_WEB_PROVIDER` → default `"tavily"`; supports `tavily | exa | brave | serper | none`. Missing key or `none` → `WebSearchResponse(disabled_reason=...)` (never raises).
- `orqest.tools.web_fetch(url, timeout_s, max_chars=8000)` — plain GET, returns `WebFetchResult(url, status_code, content_type, text, truncated)`.

## What's Next

| Phase | Status | Notes |
|-------|--------|-------|
| 1a. Orchestration (Pipeline / Parallel / Router / RefinementLoop) | ✅ shipped | |
| 1b. Core Uplift (HookRunner, BaseSessionState, CompoundTool) | ✅ shipped | |
| 1c. Batteries (Workbench, SubAgentTool, ExecutionPlan, EventBusPublishHook, SSESidecar, web tools) | ✅ shipped | |
| 2. Memory (`MemoryStore`, `LocalMemoryStore`, `MemoryConfig`) — semantic + episodic + procedural | ✅ shipped | Supabase/pgvector backend still TODO |
| 3. Autonomy (`AgentSpec`, `AgentFactory`, `ToolRegistry`, `MetaOrchestrator`) | ✅ shipped | `ToolSandbox` for generated-code safety not yet present |
| 4. Observability (`Span`, `Tracer`, `JSONTracer`, `EventBus`, `EventBusPublishHook`, `sse_sidecar`) | ✅ shipped | Optional OTEL export still TODO |
| 5. MCP Server + Client + auto-wire (`get_or_discover`, `DiscoveryHook`, `PermissionGate`) | ✅ shipped | |
| 6. Self-healing primitives (`Watchdog` / `Detection` / `RecoveryAction` / `WatchdogHook` / `FallbackModel` / `HealingRunner`) | ✅ shipped (2026-04-25) | |
| 7. Metacognition primitives (`EnrichedOutput`, `ConfidenceProtocol`, `MetacognitionHook`, integrations) | ✅ shipped (2026-04-25) | |
| 8. Generative UI (`UIComponentSpec[T]`, `ComponentRegistry`, `UIEmitter`, 17 first-party components across 3 layers) | ✅ shipped (2026-04-25) | |

**All five novel vision features ship.**

Outstanding work:
- **Concept docs** — ✅ shipped 2026-05-02; mkdocs nav wires all 24 concept docs under three groups (Composition / Memory & Cognition / Production) plus the new `reasoning` and `skills` concept pages.
- **Production memory backend** — Supabase pgvector (known gap; purely additive — `MemoryStore` Protocol and `MemoryConfig` already accommodate it).
- **`ToolSandbox`** — generated-tool-code safety surface (Phase 3's deferred safety item; relevant for agents that author + run their own tools).
- **PyPI release pipeline** — `0.1.0` and `0.2.0` are cut in CHANGELOG; not yet published to PyPI.

## Known Doc Gaps (to fix when touched)

- `README.md` carries the current elevator pitch.
- `mkdocs.yml` nav wires all 24 concept docs under three groups; `mkdocs build --strict` is clean.
- `CHANGELOG.md` cut into `[0.0.1] - 2025-07-21`, `[0.1.0] - 2026-04-24` (Phases 2–5), `[0.2.0] - 2026-04-25` (Waves 1–3), `[0.3.0] - 2026-05-14` (the reconcile pass), `[0.4.0] - 2026-05-14` (the advance pass — preview tier finished into Tier 1), and `[0.8.0] - 2026-05-23` (`orqest.optimization` battery + Tier-2 Docker sandbox + per-user persisted MCP tool library + runtime topology design + dynamic tool spawning + reasoning); fresh `[Unreleased]` for the next ship.

## Operating Mode

### Plan Mode First

Default to Plan Mode for any non-trivial change. If the task touches more than one file or introduces new behavior, enter Plan Mode before writing code. Trivial edits (typo, rename, single-line fix) skip planning.

### Tracer Bullets

New batteries land as a thin end-to-end slice first. Get two agents talking through the minimal wiring, then extract the pattern from working code — don't design the abstraction upfront.

### Self-Improvement

When a user correction or a failed approach reveals a convention, write it down. Small, targeted notes accumulate into project memory faster than retroactive doc passes.

## Global + Project Skills

Global agents live in `~/.claude/skills/` and are available from any repo:

| Agent | When to use for Orqest |
|-------|------------------------|
| `/g-orchestrator` | **Primary.** Has persistent knowledge of Orqest architecture, roadmap, principles. Use for design, build, or research on this repo. |
| `/g-strategist` | Architecture brainstorming with Gemini for roadmap-scale decisions. |
| `/g-specwright` | Spec-driven TDD before touching a new battery. |
| `/g-auditor` | Audit a plan for hidden assumptions before execution. |
| `/g-critic` | Read-only adversarial review before merge. |
| `/g-pragmatist` | Audit for SOLID / DRY / YAGNI / ETC violations. |
| `/g-chronicler` | Concept docs, ADRs, CHANGELOG, README. |
| `/g-scout` | Evaluate a competing framework (LangGraph, CrewAI, AutoGen, Semantic Kernel) before importing a pattern. |
| `/g-sre` | GitHub Actions, PyPI release pipeline, docs deploy. |

The **gstack** meta-skill (browse, qa, ship, investigate, checkpoint, codex, review, design-*, etc.) is linked into this repo at `.claude/skills/gstack -> ~/.claude/skills/gstack`. The browse skill binary resolves the project-local path first (`$ROOT/.claude/skills/gstack/browse/dist/browse`) and falls back to global, so both work.

### Recommended workflow

1. `/g-orchestrator` (design) → 2. `/g-strategist` or `/g-scout` if the design needs external grounding → 3. `/g-auditor` (assumption check) → 4. `/g-specwright` (spec + tests) → implement → 5. `/g-critic` + `/g-pragmatist` (review) → 6. `/g-chronicler` (docs) → 7. `/ship` (PR) → `/land-and-deploy`.

## References

- `/principles` skill (`.claude/skills/principles/SKILL.md`) — Pragmatic Programmer rules for this codebase (canonical). Invoke when writing, reviewing, or refactoring orqest code.
- `/orqest` skill (`orqest/skills/orqest/SKILL.md`, symlinked into `.claude/skills/orqest/`) — bundled usage skill shipped with the package. Decision tree + 5 wire-up patterns + 9 battery-specific references under `references/`. Distributed via `python -m orqest.skills install`. Drift-checked by `tests/skills/test_skill_drift.py` — every `from orqest…` import resolves on each run.
- `docs/` — MkDocs site: concept docs + API reference. Every new battery must add a `docs/concepts/<name>.md` with a runnable snippet.
- `CHANGELOG.md` — Keep-a-Changelog format.
