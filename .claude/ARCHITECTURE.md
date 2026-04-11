# Architecture

## Module Dependency Map

```
orqest/
├── __init__.py          → re-exports config.py + hooks.py + orchestration/
├── config.py            → standalone (no internal deps)
├── hooks.py             → standalone (loguru only)
├── agents/
│   ├── __init__.py      → re-exports agents/ public API
│   ├── base_agent.py    → depends on: state, context_manager, llm_model, load_sys_prompt
│   ├── state.py         → standalone (pydantic models only)
│   ├── session_state.py → depends on: state (extends GlobalState)
│   ├── compound_tool.py → depends on: base_agent, hooks
│   ├── tool_wrapper.py  → depends on: base_agent, state
│   └── context_manager.py → depends on: token_counter
├── orchestration/
│   ├── __init__.py      → re-exports all orchestration primitives
│   ├── types.py         → standalone (dataclasses + enums only)
│   ├── step.py          → depends on: base_agent, state
│   ├── pipeline.py      → depends on: step, types
│   ├── parallel.py      → depends on: step
│   ├── router.py        → depends on: step, state, base_agent
│   └── loop.py          → depends on: step, base_agent
├── utils/
│   ├── llm_model.py     → standalone (lazy provider imports)
│   └── token_counter.py → standalone (pure math)
└── io_utils/
    └── load_sys_prompt.py → standalone (filesystem only)
```

## Key Design Decisions

### Generic Typing (`BaseAgent[StateT, OutputT]`)
Agents are parameterized by state and output types. Enables compile-time validation,
IDE autocompletion, and self-documenting agent interfaces.

### Dual-Layer State (`GlobalState`)
- `messages` — app-level conversation log (role/content dicts for serialization)
- `message_history` — raw pydantic-ai ModelMessage objects for `Agent.run()`
Avoids lossy conversion between formats.

### History Processor Pipeline
Pure functions chained: ContextManager.compact() → budget_tool_results() → keep_recent_messages().
Composable and trivially testable.

### Lazy Provider Imports (`resolve_model()`)
Provider SDKs imported lazily inside `resolve_model()`. Users only need the SDK for their chosen provider.

### Agent-as-Tool (`as_tool()`)
Wraps any BaseAgent as a pydantic-ai Tool. Creates fresh GlobalState per invocation (stateless by design).

### Step Protocol (Orchestration)
A step is anything that transforms input to output. `BaseAgent` and async functions are both valid steps,
auto-coerced via `_coerce_step()`. This makes pipelines composable with simple transformations.

### Fire-and-Forget Hooks
HookRunner catches and logs hook errors at WARNING level, never propagating them. Hooks are optional
(hasattr check before calling). This ensures hooks never break agent execution.

### Session Serialization
BaseSessionState handles ModelMessages (which are dataclasses, not Pydantic models) via
`ModelMessagesTypeAdapter`. Corrupt data is handled gracefully at the deserialization boundary.

### CompoundTool Pattern
Universal pattern: agent produces output → executor acts on it → state updated. With hooks around
the executor step. Extracted from numatics_ai's orchestrator — generic enough for any domain.

### Token-Aware Context Management
Three progressive compaction layers:
1. Tool result snipping (budget_tool_results) — any time
2. Turn summarization at 60% capacity
3. Emergency truncation at 85% capacity
Thresholds tunable. Heuristic 3.5 chars/token avoids tiktoken dependency.

## Extension Points

| To add... | You need to... |
|-----------|---------------|
| New provider | Add entry to `_build_registry()` in `llm_model.py` |
| New history processor | Write pure function, pass to `BaseAgent(history_processors=[...])` |
| New agent | Subclass `BaseAgent[StateT, OutputT]`, implement `_run_implementation()` |
| New composition pattern | Use Step protocol and existing orchestration primitives |
| Custom state fields | Subclass `GlobalState` or `BaseSessionState` |
| New pipeline step | Implement `Step` protocol or pass an async function (auto-coerced) |
| Custom merge strategy | Write a function `(list[Any]) -> OutputT` for `Parallel(merge=...)` |
| Custom routing logic | Use `Router(classifier=my_async_fn)` or `Route(condition=my_predicate)` |
| Custom evaluation | Write evaluator function returning `EvalResult` for `RefinementLoop` |
| Lifecycle hooks | Implement `ToolHook` protocol (any subset of methods), pass to `HookRunner` |
| Session persistence | Subclass `BaseSessionState`, use `serialize()`/`deserialize()` |
| Compound tools | Create `CompoundTool(agent, executor, state_updater, hooks)` |

## Planned Extensions (Not Yet Built)

| Module | Purpose | Phase |
|--------|---------|-------|
| `orqest/memory/` | MemoryStore protocol + SQLite/Supabase backends | 2 |
| `orqest/autonomy/` | AgentFactory, MetaOrchestrator, ToolRegistry | 3 |
| `orqest/observability/` | Tracer, EventBus | 4 |
| `orqest/mcp/` | FastMCP server for Claude Code integration | 5 |
| `orqest/resilience/` | Watchdog, diagnostic retry | 6 |
