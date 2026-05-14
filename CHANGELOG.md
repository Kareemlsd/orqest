# Changelog

All notable changes to Orqest are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_(empty — ready for the next ship)_

## [0.2.0] - 2026-04-25

The cognitive-substrate completion. Three implementation waves landed in sequence on the same day (Wave 1: HookDecision + procedural memory + metacognition; Wave 2: healing + MCP auto-wire; Wave 3: generative UI). Test suite: 360 → 612 (+252).

### Added

**`orqest.metacognition` (Wave 1.3 — vision feature #3 "Metacognition primitives"):**
- `EnrichedOutput[OutputT]` — Pydantic generic pairing an output with `confidence` (`float | None` in `[0, 1]`), `uncertainty_targets: list[str]`, `capability_boundary: bool`, `protocol_name`, and free-form `metadata`
- `ConfidenceProtocol` Protocol + three concrete strategies: `StructuredOutputProtocol` (zero-cost; lifts `self_confidence`/`uncertain_about`/`outside_my_capability` off the agent's own `OutputT`), `LLMSelfRatingProtocol` (+1 LLM call; rater agent emits JSON, markdown-fence-tolerant parser), `EnsembleProtocol(k=N)` (+k–1 parallel calls; pairwise-agreement confidence)
- `MetacognitionHook` — `ToolHook` that emits `metacognition.confidence` events whenever a tool result is an `EnrichedOutput`
- `MetacognitionConfig` frozen dataclass with `redecompose_threshold` / `max_redecompositions` / `confidence_floor`
- `confidence_salience` / `recency_salience` — pure salience scorers for `ContextManager` integration
- `BaseAgent.run_enriched(state, *, confidence_protocol=None) -> EnrichedOutput[OutputT]` (additive; `run` untouched)
- `BaseAgent` ctor gains keyword-only `confidence_protocol` for an agent-level default
- `RefinementLoop` ctor gains `confidence_threshold: float | None` (new exit reason `"confident"`) and `agent_self_eval: BaseAgent | None`
- `SubAgentResult.confidence` / `uncertainty_targets` / `capability_boundary` (additive optional fields); `SubAgentTool.run(use_enriched=True)` lifts the final-iteration enrichment
- `ContextManager(salience_fn=...)` — pluggable per-message salience scorer; emergency truncation rescues high-salience old messages
- `MetaOrchestrator(metacognition: MetacognitionConfig | None = None)` — re-decomposes remaining subtasks when `_extract_confidence(result.output) < redecompose_threshold`

**`orqest.healing` (Wave 2 — vision feature #4 "Self-healing primitives"):**
- `HookDecision` discriminated union: `Continue` / `Skip(reason, stub_result)` / `Redirect(new_args, new_tool, reason)` / `Abort(reason)` (Wave 1.1 — also a Wave 2 prerequisite)
- `HookAbortError` — propagated when a hook returns `Abort`
- `ToolHook` protocol upgrade: methods may return `HookDecision | None`. `HookRunner._safe_call` auto-wraps `None` → `Continue`. `HookRunner._aggregate` first-non-Continue-wins with `Abort` short-circuit (Wave 1.1)
- `CompoundTool.run`, `run_with_retry`, `MetaOrchestrator._execute_subtask` honor `Skip` / `Redirect` / `Abort` (Wave 1.1)
- `Watchdog` Protocol + `Detection` Pydantic model (Wave 2.C)
- `StallDetector` (timeout on open tool calls, idempotent subscribe), `LoopDetector` (sliding window of `(tool_name, args_hash)`), `RegressionDetector` (subscribes to `metacognition.confidence` events; graceful no-op without metacog) (Wave 2.C)
- `RecoveryAction` discriminated union: `RetrySameTool` / `RetryDifferentModel` / `EscalateToUser` / `AbortRun` / `DiscoverAndRetry` + `default_policy` (Wave 2.C)
- `WatchdogHook` — `ToolHook` mapping Detection → policy → `HookDecision`. Emits `healing.action` events (Wave 2.C)
- `FallbackModel` — subclasses `pydantic_ai.models.Model`; sticky failover; transient classifier (5xx/timeout → fall back; auth/validation → propagate); emits `healing.model_fallback` (Wave 2.C)
- `resolve_model_with_fallback(models, *, api_key, bus, transient_predicate)` — accepts a chain; per-provider key map with graceful skip on missing keys (Wave 2.C)
- `HealingRunner` async context manager — wires watchdogs to a bus, runs poll loop, emits `healing.detection` events, owns the `WatchdogHook` and (optional) `FallbackModel` (Wave 2.C)
- `Workbench.with_healing(config, *, api_key=...)` convenience factory (lazy import) (Wave 2.C)
- `HealingConfig` frozen dataclass (Wave 2.C)
- `ToolRegistry.get_or_discover(name, *, discovery, manager, permission, audit_bus, max_servers)` — deliberate auto-discovery path (Wave 2.D)
- `DiscoveryHook` — `ToolHook` recovering from "tool not found" runtime errors via MCP discovery; returns `Redirect(new_tool=name)` after registration (Wave 2.D)
- `PermissionGate` Protocol + `AllowAll` / `DenyAll` (default) / `AllowList` (regex) (Wave 2.D)
- Audit-log events: `discovery.requested` / `discovery.connected` / `discovery.denied` / `discovery.failed` (Wave 2.D)

**`orqest.ui` (Wave 3 — vision feature #5 "Generative UI"):**
- `UIComponentSpec[T]` — generic Pydantic with `component_type` `Literal` discriminator, `component_id`, typed `data: T`, `metadata`, `created_at`
- `UIDeltaEvent` — partial update with `op: Literal["replace","merge","append","remove"]` + dot-path + value
- `UIDeltaOp` type alias
- `ComponentRegistry` per-Workbench (no module singleton): `register`, `get`, `list_types`, `validate_payload`
- `default_registry()` — pre-loads first-party components
- `UIEmitter(bus)` — `init` / `delta` / `remove` convenience over `EventBus`
- `ui_init_event_type` / `ui_delta_event_type` / `ui_remove_event_type` helpers (event-type convention `ui.<component_type>.{init,delta,remove}`)
- First-party components: `PlanComponent`, `ChartComponent` (line/bar/scatter/pie/heatmap with typed `ChartSeries`), `TableComponent` (typed `TableColumn`), `FormComponent` (typed `FormField`), `TakeoverDialogComponent` (confirm/input/choice), plus declarative grammars (`VegaChartComponent`, `MermaidComponent`, `LatexComponent`, `JsonViewerComponent`) and the `SandboxedHTMLComponent` escape hatch
- `ExecutionPlan.enable_ui_events(*, component_id="plan")` — opt-in flag-gated dual emission of `ui.plan.init`/`ui.plan.delta` alongside legacy `plan.init`/`plan.task.updated`
- `ExecutionPlan.as_component()` — wraps the plan as a `PlanComponent`
- `Workbench(ui_registry=..., auto_register_first_party_ui=True)` ctor kwargs

**Cognitive memory typology (Wave 1.2 — vision feature #2 "Cognitive memory typology" completion):**
- `MemoryEntry.memory_type` extended to `Literal["semantic", "episodic", "procedural"]`
- `Skill` / `ToolCallSpec` / `SkillExample` Pydantic shapes (procedural payload in `MemoryEntry.structured_content`)
- `MemoryEntry.structured_content: dict[str, Any] | None` (validation gated to `memory_type == "procedural"`)
- `MemoryFilter.skill_name` / `skill_min_version` for procedural filtering
- `RetrievalStrategy` Protocol + `SemanticStrategy` (legacy FTS5/LIKE behavior preserved) / `EpisodicStrategy` (`ORDER BY created_at DESC`) / `ProceduralStrategy` (exact trigger match + optional injected fuzzy judge)
- `default_strategy_table()` — the per-kind dispatch table consumed by `LocalMemoryStore`
- `LocalMemoryStore(strategies=...)` — strategy override for custom backends
- Best-effort `ALTER TABLE` migration for the `structured_content` column
- `MemoryConfig` extended with `semantic` / `episodic` / `procedural` `PerKindConfig` fields (TTL / decay / version-on-edit)
- `MetaOrchestrator._find_or_spawn` dual-write migration: persists both episodic mirror (legacy) and procedural `Skill` entries; recall is procedural-first with episodic fallback

**Test suite:** 360 → 612 at wave-3 ship (+252 across the three waves; 360 pre-existing tests stayed green at every wave boundary). Subsequent consumer-side polish (2026-04-26) brought the suite to 655.

## [0.1.0] - 2026-04-24

Phases 2–5 of the original Orqest roadmap stabilized: Memory, Autonomy, Observability, and MCP. The substrate that the Wave 1–3 cognitive features in 0.2.0 build on.

### Added

**`orqest.memory` (Phase 2):**
- `MemoryStore` Protocol — `store`, `recall`, `forget`, `update_reliability`, `count`
- `MemoryEntry` — content + `memory_type` (initially `"semantic" | "episodic"`) + source agent + confidence + reliability score + metadata + access tracking
- `MemoryFilter` — query constraints (memory_type, source_agent, min_confidence, before/after timestamps)
- `LocalMemoryStore` — SQLite + FTS5 backend (with `LIKE` fallback when FTS5 unavailable). Lazy init; best-effort error handling (logged, never raised). Self-healing reliability decay on failure.
- `MemoryConfig` — frozen dataclass for backend selection and embedding model

**`orqest.autonomy` (Phase 3):**
- `AgentSpec` / `ToolSpec` — serializable contracts; LLM can emit these as structured output
- `AgentFactory.spawn(spec) -> DynamicAgent` — builds a Pydantic output model from JSON Schema via `pydantic.create_model()`; resolves tools from the registry; injects constraints into the system prompt
- `ToolRegistry` — `register`, `get`, `search(query, k)` (keyword scoring), `list_all`, `remove`, dunder methods
- `MetaOrchestrator(planner_agent, registry, default_model)` — goal → `TaskDecomposition` → per `SubTask` spawn-or-find agent → execute → `SubTaskResult` → aggregated `ExecutionResult`
- `DynamicAgent` extends `BaseAgent[GlobalState, BaseModel]`

**`orqest.observability` (Phase 4):**
- `Span` — `trace_id`, `span_id`, `parent_span_id`, `name`, `agent_name`, timing, `status`, `attributes`, `events`
- `Tracer` Protocol; `JSONTracer` is the default in-memory implementation (no external deps)
- `AgentEvent` — frozen immutable event (`event_type`, `agent_name`, `timestamp`, `data`, `span_id`, `trace_id`)
- `EventBus` — in-process pub/sub; `subscribe(event_type)`, `subscribe_all`, `emit(event)`. Handler exceptions logged and discarded (fire-and-forget)
- `EventBusPublishHook` — bridges `ToolHook` → `EventBus`; emits `tool.before`, `tool.after`, `tool.error` with configurable preview truncation
- `sse_sidecar(bus, replay=(), heartbeat_s=15.0, queue_size=256)` — async iterator yielding SSE-formatted strings; ring-buffered against slow consumers; optional historical replay for reconnection

**`orqest.workbench`:**
- `Workbench` — runtime container bundling memory + tracer + event_bus + recent_events ring buffer

**`orqest.compound`:**
- `SubAgentTool[StateT, ResultT]` + `SubAgentResult` — captures agent → executor → state-update → optional refinement; refinement-loop integrated

**`orqest.plan`:**
- `ExecutionPlan`, `PlanTask`, `PlanSubtask`, `PlanStatus` — typed multi-step workflow tracking; `to_sse_init()` is byte-stable as a frontend contract

**`orqest.mcp` (Phase 5):**
- `MCPServerConfig` / `MCPConfig` — explicit server definitions + auto-discovery toggle
- `MCPConnection(config)` — single-server lifecycle: `await connect()` → `.tools` → `await disconnect()`
- `MCPServerManager` — multi-server orchestration, `async with` context manager, `connect_all`, `get_all_tools` (flat list), `search_tools`
- `MCPToolAdapter.adapt[_many]` — MCP tool definitions → pydantic-ai `Tool` instances (graceful error-string return wrapper)
- `MCPDiscovery.search(query, max_results)` — online discovery (registry + well-known manifests + web fallback)
- Auto-discovery scans `~/.claude.json`, `~/.claude/claude.json`, `~/.config/Claude/claude_desktop_config.json`
- `create_orqest_server(factory, registry, meta, default_model, api_key)` — FastMCP server exposing `create_agent`, `run_agent`, `solve_goal`, `list_agents`. Run with `python -m orqest.mcp.server`

**`orqest.tools.web`:**
- `web_search(query, k, provider, api_key)` — pluggable provider strategy (tavily / exa / brave / serper); graceful degradation when key missing
- `web_fetch(url)` — plain GET with `WebFetchResult(url, status_code, content_type, text, truncated)`

**Multi-modal prompts and streaming:**
- `BaseAgent.call_model` / `call_model_stream` / `stream_output` / `stream_events` accept `str | Sequence[UserContent]` (images, PDFs, audio, video via pydantic-ai's `ImageUrl` / `DocumentUrl` / `AudioUrl` / `VideoUrl` / `BinaryContent`)
- `Prompt` type alias (`str | Sequence[UserContent]`) exported from `orqest.agents`
- `call_model_stream()` — async context manager for streaming with history wiring
- `stream_output()` — async generator yielding partial structured output as the LLM generates tokens
- `stream_events()` — async generator yielding all agent events including tool call/result visibility

**Composition extensions:**
- `as_tool()` — wrap any `BaseAgent` as a pydantic-ai `Tool` for stateless orchestrator invocation
- `call_model()` on `BaseAgent` — multi-turn conversation support with automatic history wiring
- `CompoundTool` pattern — agent → executor → state update with HookRunner dispatch
- `run_with_retry()` — exception-based retry with default enrichment
- `ContextManager` — token-aware three-tier compaction (tool-result snip → turn summarization at 60% → emergency truncation at 85%)
- Documentation site (MkDocs Material) with concept docs + auto-generated API reference

### Changed
- `GlobalState.message_history` typed as `list[ModelMessage]` instead of `list[Any]`

## [0.0.1] - 2025-07-21

### Added
- `BaseAgent[StateT, OutputT]` — generic, async-first abstract base class for agents
- `GlobalState` — conversation state with app-level messages and pydantic-ai message history
- `keep_recent_messages()` — history truncation preserving first message and turn integrity
- `resolve_model()` — multi-provider model routing (OpenAI, Anthropic, Google, OpenRouter) using `provider:model_id` format
- `OrqestConfig` — frozen dataclass for runtime configuration
- `load_config()` and `get_default_config()` — explicit config loading with no import-time side effects
- `load_sys_prompt()` — system prompt file loader with upward directory search
- Tool and toolset registration on `BaseAgent`
- Custom history processor support
- Example notebook `01_basic_agent` with single agent and structured output
- Test suite covering all modules
