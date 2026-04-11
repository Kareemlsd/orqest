# Changelog

All notable changes to Orqest are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

**Orchestration**

- `Pipeline` — sequential step execution with STOP/SKIP/RETRY error strategies and streaming events
- `Parallel` — concurrent step execution with merge strategies (`collect_all`, `first_wins`, custom) and timeout
- `Router` — conditional routing with rule-based conditions and LLM-driven classification, fallback support
- `RefinementLoop` — iterative refinement with evaluator feedback, convergence detection, and timeout
- `Step` protocol — unified interface for agents and async functions as executable steps
- `AgentStep` / `FunctionStep` — concrete step implementations with auto-coercion from `BaseAgent` and callables

**Hooks & Lifecycle**

- `HookRunner` — fire-and-forget hook dispatcher with error resilience (broken hooks never crash agents)
- `ToolHook` protocol — partial implementation support (only implement `before_tool`, `after_tool`, or `on_error` as needed)

**Session Persistence**

- `BaseSessionState` — extends `GlobalState` with `session_id`, `created_at`, and JSON-safe serialization
- ModelMessage round-tripping via `ModelMessagesTypeAdapter`
- Corrupt data resilience on deserialization (falls back to empty history)

**Compound Tools**

- `CompoundTool` — agent-decides, system-acts pattern with hook integration and optional state updater

**Memory**

- `MemoryStore` protocol — pluggable memory backend interface (`store`, `recall`, `forget`, `update_reliability`, `count`)
- `LocalMemoryStore` — SQLite backend with FTS5 full-text search and LIKE fallback
- `MemoryEntry` — memory unit with confidence, reliability score, embeddings, and access tracking
- `MemoryFilter` — query-time constraints (type, source, confidence, reliability)
- `MemoryConfig` — configuration for backend selection and embedding settings
- Self-healing reliability decay (0.7x per failure, auto-prune below 0.1)

**Observability**

- `Span` — structured trace span with parent-child relationships and attributes
- `Tracer` protocol — pluggable trace collection backend
- `JSONTracer` — in-memory tracer with JSON export, zero external dependencies
- `AgentEvent` — lightweight event with trace correlation (`span_id`, `trace_id`)
- `EventBus` — in-process pub/sub with type-specific and global handlers, fire-and-forget error handling

**Other**

- `as_tool()` — wrap any `BaseAgent` as a pydantic-ai `Tool` for stateless orchestrator invocation
- `call_model()` on `BaseAgent` — multi-turn conversation support with automatic history wiring
- `ContextManager` — token-aware progressive compaction (summarize at 60%, truncate at 85%)
- `budget_tool_results()` — history processor for managing tool result token budgets
- Example notebooks: `01_basic_agent`, `02_agent_as_tool`, `03_streaming`, `04_pipeline`, `06_parallel_and_router`, `07_hooks_and_session`
- Documentation site with MkDocs Material — concept pages for all major features

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
