# Changelog

All notable changes to Orqest are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (2026-04-25 — three implementation waves landed the same day)

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
- First-party components: `PlanComponent`, `ChartComponent` (line/bar/scatter/pie/heatmap with typed `ChartSeries`), `TableComponent` (typed `TableColumn`), `FormComponent` (typed `FormField`), `TakeoverDialogComponent` (confirm/input/choice)
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

**Test suite: 360 → 612** (+252 across the three waves; 360 pre-existing tests stayed green at every wave boundary).

### Added (pre-2026-04-25)
- Multi-modal prompt support on `BaseAgent` — `call_model()`, `call_model_stream()`, `stream_output()`, and `stream_events()` now accept `str | Sequence[UserContent]`, enabling images, PDFs, audio, and video via pydantic-ai's `ImageUrl`, `DocumentUrl`, `AudioUrl`, `VideoUrl`, and `BinaryContent` types
- `Prompt` type alias (`str | Sequence[UserContent]`) exported from `orqest.agents`
- `call_model_stream()` on `BaseAgent` — async context manager for streaming with history wiring
- `stream_output()` on `BaseAgent` — async generator yielding partial structured output as the LLM generates tokens
- `stream_events()` on `BaseAgent` — async generator yielding all agent events including tool call/result visibility
- Example notebook `03_streaming` demonstrating streaming, tool event visibility, and transport integration
- Streaming concept page in documentation
- `as_tool()` — wrap any `BaseAgent` as a pydantic-ai `Tool` for stateless orchestrator invocation
- `call_model()` on `BaseAgent` — multi-turn conversation support with automatic history wiring
- Multi-turn conversation example in `01_basic_agent` notebook
- Example notebook `02_agent_as_tool` demonstrating the agent-as-tool composition pattern
- Documentation site with MkDocs Material

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
