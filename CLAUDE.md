# Orqest — Agent Instructions

## What This Is

Orqest is a Python framework for building autonomous agentic AI systems on top of pydantic-ai. It ships typed agent primitives, orchestration patterns, lifecycle hooks, session persistence, agent composition, memory, dynamic agent spawning, MCP client + server, and first-class observability.

**Design principle:** *"Core Orqest manages the shape and flow of intelligence; Extensions manage the matter and action of the domain."*

**Domain-agnostic litmus test:** "Can a developer building a headless coding assistant use this feature without knowing what Polymath is?" If no, it belongs in the consumer, not Orqest.

**Current version:** `0.0.1` (`pyproject.toml`). **All five novel vision features shipped (2026-04-25)** — runtime agent design, cognitive memory typology (semantic / episodic / procedural), metacognition primitives, self-healing primitives, generative UI. See `.claude/VISION.md` for the strategic frame and `.claude/IMPLEMENTATION_2026-04-25.md` for the three-wave ship plan.

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
│   └── loop.py              # RefinementLoop (evaluator + convergence detection)
│
├── memory/                  # Cognitive memory typology (semantic / episodic / procedural)
│   ├── store.py             # MemoryStore protocol, MemoryEntry, MemoryFilter, Skill / ToolCallSpec / SkillExample
│   ├── local.py             # LocalMemoryStore (SQLite + FTS5; strategy-dispatch for per-kind retrieval)
│   ├── strategies.py        # SemanticStrategy, EpisodicStrategy, ProceduralStrategy (+ injected fuzzy judge)
│   └── config.py            # MemoryConfig + PerKindConfig (TTL, decay, version-on-edit)
│
├── autonomy/                # Runtime agent spawning (Phase 3 — shipped)
│   ├── spec.py              # AgentSpec, ToolSpec (serializable contracts)
│   ├── factory.py           # AgentFactory → DynamicAgent via pydantic.create_model()
│   ├── registry.py          # ToolRegistry (register / get / search / list_all)
│   └── meta.py              # MetaOrchestrator (goal → decomposition → spawn → execute)
│
├── observability/           # Phase 4 — shipped
│   ├── tracer.py            # Span, Tracer protocol, JSONTracer (in-memory, JSON export)
│   ├── events.py            # AgentEvent, EventBus (pub/sub, fire-and-forget)
│   ├── event_bus_hook.py    # EventBusPublishHook (ToolHook → EventBus bridge)
│   └── sse_sidecar.py       # sse_sidecar() — SSE stream w/ replay + heartbeat + ring buffer
│
├── workbench/               # Runtime container (bundles memory + tracer + bus + recent-events buffer)
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
│   ├── discovery.py         # MCPDiscovery, DiscoveredServer (online + well-known search)
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
│   └── components/          # First-party: Plan / Chart / Table / Form / TakeoverDialog
│
├── tools/                   # First-party reusable pydantic-ai Tools
│   └── web.py               # web_search, web_fetch + result models (tavily/exa/brave/serper)
│
├── utils/
│   ├── llm_model.py         # resolve_model() — lazy registry (OpenAI, Anthropic, Google, OpenRouter)
│   └── token_counter.py     # estimate_tokens() (heuristic 3.5 chars/token)
│
└── io_utils/
    └── load_sys_prompt.py   # load_sys_prompt() — upward search for system_prompts/ dir
```

### Public API (root re-exports from `orqest/__init__.py`)

`OrqestConfig`, `load_config`, `get_default_config`, `HookRunner`, `ToolHook`, `HookDecision` (`Continue` / `Skip` / `Redirect` / `Abort`), `HookAbortError`, `Pipeline`, `Parallel`, `Router`, `RefinementLoop`, `ExecutionPlan`, `PlanStatus`, `PlanSubtask`, `PlanTask`, `Workbench`, `EnrichedOutput`, `MetacognitionConfig`, `HealingConfig`.

Other subsystems are imported via their submodules (`from orqest.memory import LocalMemoryStore, Skill`, `from orqest.observability import EventBus, sse_sidecar`, `from orqest.compound import SubAgentTool`, `from orqest.metacognition import StructuredOutputProtocol, MetacognitionHook`, `from orqest.healing import HealingRunner, StallDetector, FallbackModel`, `from orqest.ui import UIComponentSpec, ChartComponent, UIEmitter`, etc.) so the root namespace stays small.

### Tests

Mirrors source layout under `tests/`. As of latest collect: **655 tests** (was 360 baseline + 252 added across the three implementation waves + a handful added with the consumer-side polish). Coverage spans agents, orchestration, memory, mcp, autonomy, observability, workbench, compound, plan, tools, utils, io_utils, **metacognition, healing, ui**, plus root-level tests for config, hooks, hook_decision, budget_tool_results, context_manager.

### Examples

`examples/01_basic_agent`, `02_agent_as_tool`, `03_streaming`, `04_pipeline`, `06_parallel_and_router`, `07_hooks_and_session`, `08_memory`, `09_observability` — all tested with real LLMs. `05_refinement_loop/` exists as a skeleton (not yet authored); worth filling in next time someone touches `RefinementLoop`.

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

## Dev Commands

```bash
# Install in editable mode (local venv)
uv pip install -e .

# Run full suite (655 tests)
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
- `resolve_model()` — lazy registry (OpenAI, Anthropic, Google, OpenRouter); missing SDKs silently skipped

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
- `LocalMemoryStore` — SQLite + FTS5 (with LIKE fallback), lazy init, errors swallowed. Recall dispatches to a per-kind :class:`RetrievalStrategy` (Semantic / Episodic / Procedural). Also exposes `list_recent(*, memory_type=None, limit=50)` (added 2026-04-26) — browse-style enumeration newest-first that complements the query-driven `recall(...)`. Used by consumer-side surfaces that want a "memory inspector" view without issuing a search.
- `ProceduralStrategy` — exact-match on `structured_content.trigger` (case-insensitive substring); optional injected `fuzzy_judge` callable for near-miss queries.
- `MemoryConfig` + `PerKindConfig` — frozen dataclass with per-kind TTL / decay / version-on-edit policies.

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
- `MCPDiscovery.search(query, max_results)` — online discovery (registry + well-known manifests + web fallback). Returns `DiscoveredServer` records.
- Auto-discovery scans `~/.claude.json`, `~/.claude/claude.json`, `~/.config/Claude/claude_desktop_config.json`.
- `create_orqest_server(factory, registry, meta, default_model, api_key)` — FastMCP server exposing `create_agent`, `run_agent`, `solve_goal`, `list_agents`. Run with `python -m orqest.mcp.server`.
- **Auto-wire (2026-04-25):** `ToolRegistry.get_or_discover` (deliberate path) + `DiscoveryHook` (opportunistic recovery from "tool not found" errors) + `PermissionGate` (`AllowAll` / `DenyAll` / `AllowList` regex; default `DenyAll` — discovery is opt-in). Audit-log emission via `discovery.requested` / `discovery.connected` / `discovery.denied` / `discovery.failed` events.

### Phase 6 — Self-healing primitives ✅ (vision feature #4)

- `Watchdog` Protocol + `Detection` Pydantic model. Detectors observe; the policy decides recovery; `WatchdogHook` translates intent into a `HookDecision`.
- `StallDetector` — flags open tool calls exceeding `timeout_s`; idempotent subscribe; suppresses double-fire on same call.
- `LoopDetector` — sliding window of `(tool_name, args_hash)` pairs; fires when count > `threshold_k`; suppression resets when pair changes.
- `RegressionDetector` — sliding window of `metacognition.confidence` events; fires on head-half-mean − tail-half-mean ≥ `drop_threshold`. Silently no-ops when no metacog events flow (graceful degradation).
- `RecoveryAction` discriminated union: `RetrySameTool` / `RetryDifferentModel` / `EscalateToUser` / `AbortRun` / `DiscoverAndRetry`. `default_policy` → `AbortRun` for every detector; consumers override via custom callable.
- `WatchdogHook(watchdogs, *, policy, bus)` — `ToolHook` whose `before_tool` consults watchdogs and returns a `HookDecision`. Emits `healing.action` events when bus is configured. **Also emits `healing.retry_initiated`** (added 2026-04-26) with `{tool_name, detector, summary, severity}` whenever the policy chooses `RetrySameTool` — feeds the chrome's healing toast surface.
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
- `RefinementLoop` ctor gains `confidence_threshold: float | None` (exit reason `"confident"` when score ≥ threshold) and `agent_self_eval: BaseAgent | None` (mutually-exclusive scoring path: synthesises `EvalResult(passed=False, score=enriched.confidence)`).
- `SubAgentResult.confidence` / `uncertainty_targets` / `capability_boundary` (additive optional fields). `SubAgentTool.run(use_enriched=True)` lifts the final-iteration enrichment onto the result.
- `ContextManager(salience_fn=...)` — pluggable per-message salience scorer; emergency truncation rescues high-salience old messages on top of the recency window. `confidence_salience` / `recency_salience` ship in `orqest.metacognition.salience`.
- `MetaOrchestrator(metacognition: MetacognitionConfig | None = None)` — re-decomposes remaining subtasks when `_extract_confidence(result.output) < redecompose_threshold`, bounded by `max_redecompositions`. The `_extract_confidence` helper reads `EnrichedOutput.confidence`, then `output.confidence`, then `output.metadata["confidence"]` — picking up the latent shape `_find_or_spawn` already prompts spawned agents to emit (`meta.py:267-272`).

### Phase 8 — Generative UI ✅ (vision feature #5)

- `UIComponentSpec[T]` — generic Pydantic with `component_type` `Literal` discriminator + `component_id` + typed `data: T` + `metadata` + `created_at`. Open extension point: third parties register their own component classes.
- `UIDeltaEvent` — partial update with `op: Literal["replace","merge","append","remove"]` + dot-path + value.
- `ComponentRegistry` — per-Workbench (not module-level singleton): `register`, `get`, `list_types`, `validate_payload`. `default_registry()` returns a registry pre-loaded with first-party components.
- `UIEmitter(bus)` — convenience facade for `init` / `delta` / `remove` events on the bus. Bus failures emit DEBUG log; never raise.
- SSE event-type conventions: `ui.<component_type>.{init,delta,remove}`. Helpers `ui_init_event_type` / `ui_delta_event_type` / `ui_remove_event_type` keep consumers decoupled from string literals.
- First-party components: `PlanComponent` (carries `PlanTask` list), `ChartComponent` (line/bar/scatter/pie/heatmap with typed `ChartSeries`), `TableComponent` (typed `TableColumn` + rows), `FormComponent` (typed `FormField` + submit event), `TakeoverDialogComponent` (confirm / input / choice).
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
| 8. Generative UI (`UIComponentSpec[T]`, `ComponentRegistry`, `UIEmitter`, 5 first-party components) | ✅ shipped (2026-04-25) | |

**All five novel vision features ship.** See `.claude/VISION.md` for the strategic frame, `.claude/IMPLEMENTATION_2026-04-25.md` for the wave-by-wave ship plan, and `.claude/AUDIT_2026-04-25.md` for the audit that drove the implementation. Per-track designs live in `.claude/designs/`.

Outstanding consumer-side work (out of Orqest core):
- **Polymath consolidation** — ✅ shipped 2026-04-25 (`demo/polymath/.claude/CONSOLIDATION_COMPLETE_2026-04-25.md`). The dedicated `ChartsTab` / `ReportTab` were absorbed into the dynamic dockview tab manifest, healing wired into `Workbench`, and sub-agent roster migrated to procedural memory.
- **Polymath cognitive surfacing** — ✅ shipped 2026-04-26. Confidence per turn, healing toasts, Memory tab (galaxy + 3-kind browser), Agents tab (roster table). See addendums in the same consolidation doc.
- **Polymath editorial redesign** — ✅ shipped 2026-04-26 from a claude.ai/design handoff. Warm-neutral oklch + amber accent + Newsreader serif + Inter Tight grotesk + the **Cognitive Gutter** (24px left rail per assistant turn — replaces the per-message confidence pill). See `demo/polymath/CLAUDE.md` for the current-state summary.
- **Concept docs** — ✅ `docs/concepts/{metacognition,healing,generative_ui,autonomy,mcp}.md` shipped 2026-05-02; mkdocs nav wires all 19 concept docs under three groups (Composition / Memory & Cognition / Production).
- **Orqest skill folder** — ✅ shipped 2026-05-02 at `.claude/skills/orqest/` (and packaged as `.skill`). The canonical playbook for Claude Code consumers; symlinked at `~/.claude/skills/orqest` for global availability.
- **Production memory backend** — Supabase pgvector (known gap; purely additive — `MemoryStore` Protocol and `MemoryConfig` already accommodate it).
- **`ToolSandbox`** — generated-tool-code safety surface (Phase 3's deferred safety item; relevant for agents that author + run their own tools).
- **PyPI release pipeline** — `0.1.0` and `0.2.0` are cut in CHANGELOG; not yet published to PyPI.

## Building With Orqest (For Claude Code)

When a developer asks to add agent capabilities to an existing application, **use the bundled skill** at `.claude/skills/orqest/` (also available globally via `~/.claude/skills/orqest`). The skill enforces a discovery-first integration loop: interview the developer → walk the existing codebase → pick the minimal Orqest surface that fits → integration plan → tracer-bullet build → produce `AGENT_HARNESS.md`. The skill folder bundles eight pattern recipes, the Vercel AI SDK + Orqest integration recipe (Polymath pattern), Python module templates, React frontend hooks (extracted from Polymath, generic-ified), and a `scaffold_agent.py` CLI.

For top-level discoverability, [`SKILLS.md`](SKILLS.md) at the repo root points at the skill folder.

## Known Doc Gaps (to fix when touched)

- `.claude/ROADMAP.md` is current as of 2026-05-02; treat this CLAUDE.md as ground truth if they ever drift.
- `.claude/ARCHITECTURE.md` rewritten 2026-05-02 as an extensibility playbook (10 named extension patterns).
- `README.md` refreshed 2026-05-02 with current elevator pitch + pointer to SKILLS.md.
- `mkdocs.yml` nav now wires all 19 concept docs under three groups; `mkdocs build --strict` clean as of 2026-05-02.
- `examples/05_refinement_loop/` shipped 2026-05-02 with `main.py` + `README.md` demonstrating `confidence_threshold` + `agent_self_eval` (Wave 1.3 metacognition integration).
- `CHANGELOG.md` cut into `[0.1.0] - 2026-04-24` (Phases 2–5) + `[0.2.0] - 2026-04-25` (Waves 1–3) on 2026-05-02; fresh `[Unreleased]` for the next ship.

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

- `.claude/PRINCIPLES.md` — Pragmatic Programmer rules for this codebase (treat as canonical).
- `.claude/ARCHITECTURE.md` — module dependency map + design decisions (some sections are stale; see "Known Doc Gaps").
- `.claude/ROADMAP.md` — long-form phase plan (status tracking is stale — this CLAUDE.md is ground truth).
- `docs/` — MkDocs site: concept docs + API reference. Every new battery must add a `docs/concepts/<name>.md` with a runnable snippet.
- `CHANGELOG.md` — Keep-a-Changelog format. `Unreleased` is currently thick.
