# Architecture

## Module Dependency Map

```
orqest/
├── __init__.py          → re-exports config.py public API
├── config.py            → standalone (no internal deps)
├── agents/
│   ├── __init__.py      → re-exports agents/ public API
│   ├── base_agent.py    → depends on: state, context_manager, llm_model, load_sys_prompt
│   ├── state.py         → standalone (pydantic models only)
│   ├── tool_wrapper.py  → depends on: base_agent, state
│   └── context_manager.py → depends on: token_counter
├── utils/
│   ├── llm_model.py     → standalone (lazy provider imports)
│   └── token_counter.py → standalone (pure math)
└── io_utils/
    └── load_sys_prompt.py → standalone (filesystem only)
```

## Key Design Decisions

### Generic Typing (`BaseAgent[StateT, OutputT]`)
Agents are parameterized by state and output types. This enables:
- Compile-time validation of composition (is agent A's output compatible with agent B's input?)
- IDE autocompletion for state fields and output attributes
- Self-documenting agent interfaces

### Dual-Layer State (`GlobalState`)
Two separate message stores exist because they serve different consumers:
- `messages` — app-level conversation log (role/content dicts for serialization to DB, UI)
- `message_history` — raw pydantic-ai `ModelMessage` objects for passing back to `Agent.run()`

This avoids lossy conversion between formats and keeps the pydantic-ai contract clean.

### History Processor Pipeline
History processing is a chain of pure functions, each taking and returning a message list:
1. `ContextManager.compact()` — token-aware progressive compaction
2. `budget_tool_results()` — truncates oversized tool results
3. `keep_recent_messages()` — sliding window with turn integrity repair

Pure functions compose cleanly and are trivially testable.

### Lazy Provider Imports (`resolve_model()`)
Provider SDKs (openai, anthropic, google-genai) are imported lazily inside `resolve_model()`.
This means:
- Users only need to install the SDK for their chosen provider
- No import-time failures for missing optional dependencies
- Adding a new provider = adding a registry entry, not changing control flow

### Agent-as-Tool (`as_tool()`)
Wraps any BaseAgent as a pydantic-ai Tool for orchestrator delegation.
Creates a fresh GlobalState per invocation — the wrapped agent is stateless.
This is intentional: tool-agents do a focused job and return, they don't need conversation context.

### Token-Aware Context Management (`ContextManager`)
Three progressive compaction layers:
1. **Tool result snipping** at any time — truncate oversized results with preview
2. **Turn summarization** at 60% capacity — summarize old tool-call pairs
3. **Emergency truncation** at 85% capacity — drop oldest messages aggressively

Thresholds are tunable. Token estimation uses a 3.5 chars-per-token heuristic
to avoid the tiktoken dependency.

## Extension Points

| To add... | You need to... |
|-----------|---------------|
| New provider | Add entry to `_build_registry()` in `llm_model.py` |
| New history processor | Write a pure function matching the processor signature, add to chain in `base_agent.py` |
| New agent capability | Compose via tool/toolset registration on BaseAgent, not inheritance |
| New composition pattern | Build on `as_tool()` for delegation, or implement new pattern (Pipeline, etc.) alongside it |
