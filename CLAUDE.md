# Orqest — Agent Instructions

## What This Is

Orqest is a Python framework for building autonomous agentic AI systems on top of pydantic-ai. It provides typed agent primitives, orchestration patterns (pipeline, parallel, routing, refinement loops), lifecycle hooks, session persistence, and agent composition — with memory, dynamic agent spawning, and MCP integration on the roadmap.

**Design principle:** *"Core Orqest manages the shape and flow of intelligence; Extensions manage the matter and action of the domain."*

**Current version:** 0.0.1 (active development — Phase 1 complete, Phase 2 in progress)

## Project Structure

```
orqest/
├── __init__.py              # Re-exports: OrqestConfig, Pipeline, Parallel, Router,
│                            #   RefinementLoop, HookRunner, ToolHook
├── config.py                # OrqestConfig dataclass + load_config() factory
├── hooks.py                 # HookRunner + ToolHook protocol (fire-and-forget lifecycle)
├── agents/
│   ├── __init__.py          # Re-exports: BaseAgent, GlobalState, BaseSessionState,
│   │                        #   CompoundTool, ContextManager, as_tool, keep_recent_messages
│   ├── base_agent.py        # BaseAgent[StateT, OutputT] + call_model() + streaming
│   ├── state.py             # GlobalState — shared conversation state
│   ├── session_state.py     # BaseSessionState — serializable state with persistence
│   ├── compound_tool.py     # CompoundTool — agent→execute→update pattern with hooks
│   ├── tool_wrapper.py      # as_tool() — wrap a BaseAgent as a pydantic-ai Tool
│   └── context_manager.py   # ContextManager — token-aware progressive compaction
├── orchestration/
│   ├── __init__.py          # Re-exports all orchestration primitives
│   ├── types.py             # ErrorStrategy, StepConfig, PipelineEvent
│   ├── step.py              # Step protocol, AgentStep, FunctionStep, StepLike
│   ├── pipeline.py          # Pipeline — sequential step execution
│   ├── parallel.py          # Parallel — concurrent execution with merge
│   ├── router.py            # Router — conditional routing (rule-based + LLM)
│   └── loop.py              # RefinementLoop — iterative refinement with evaluation
├── mcp/
│   ├── __init__.py          # Re-exports: MCPServerManager, MCPToolAdapter, MCPConfig
│   ├── config.py            # MCPServerConfig, MCPConfig
│   ├── adapter.py           # MCPToolAdapter — bridge MCP tools → pydantic-ai Tools
│   ├── client.py            # MCPConnection, MCPServerManager (multi-server lifecycle)
│   └── server.py            # create_orqest_server() — expose Orqest via FastMCP
├── utils/
│   ├── llm_model.py         # resolve_model() — multi-provider routing
│   └── token_counter.py     # estimate_tokens() — heuristic token counting
└── io_utils/
    └── load_sys_prompt.py   # load_sys_prompt() — system prompt file loader

tests/                       # Mirrors source layout — 193 tests
├── conftest.py              # Shared fixtures (OrqestConfig, TestModel)
├── test_config.py
├── test_hooks.py            # HookRunner, ToolHook protocol tests
├── test_budget_tool_results.py
├── test_context_manager.py
├── agents/
│   ├── test_base_agent.py
│   ├── test_state.py
│   ├── test_tool_wrapper.py
│   ├── test_session_state.py
│   └── test_compound_tool.py
├── orchestration/
│   ├── test_step.py
│   ├── test_pipeline.py
│   ├── test_parallel.py
│   ├── test_router.py
│   └── test_loop.py
├── utils/
│   └── test_llm_model.py
└── io_utils/
    └── test_load_sys_prompt.py

examples/                    # Progressive, docs-ready, tested with real LLMs
├── 01_basic_agent/          # Single agent + multi-turn
├── 02_agent_as_tool/        # Agent-as-tool composition
├── 03_streaming/            # Streaming patterns
├── 04_pipeline/             # Pipeline + RefinementLoop
├── 06_parallel_and_router/  # Parallel execution + conditional routing
└── 07_hooks_and_session/    # Hooks, session persistence, compound tools
```

## Key Conventions

- **Async-first**: All agent execution is async. Use `async/await` everywhere.
- **Pydantic models**: State and output types must be Pydantic BaseModel subclasses.
- **Generic typing**: Agents are `BaseAgent[StateT, OutputT]` — always specify both type params.
- **Explicit dependencies**: No import-time side effects. Functions take deps as arguments.
- **Model format**: `LLM_MODEL` uses `provider:model_id` format (e.g., `openai:gpt-4.1`).
- **pydantic-ai**: The underlying agent framework. Build on it, not around it.
- **Python 3.12+**: Minimum version. Use modern Python features.
- **Domain-agnostic litmus test**: "Can a developer building a headless Coding Assistant use this feature without knowing what Numatics AI is?"
- **Build system**: setuptools via pyproject.toml. Dependencies managed there.
- **Linting**: ruff (configured in pyproject.toml).
- **Testing**: pytest + pytest-asyncio. Run with `.venv/bin/python -m pytest tests/ -v`.
- **Changelog**: Keep a Changelog format in CHANGELOG.md.

## Dev Commands

```bash
# Install in dev mode
uv pip install -e .

# Run tests (283 tests)
.venv/bin/python -m pytest tests/ -v

# Lint
ruff check orqest/

# Docs
uv run mkdocs serve        # local with hot reload
uv run mkdocs build        # static site

# Build package
python -m build
```

## What Exists Today (Phase 1 Complete)

### Agents & State
- `BaseAgent[StateT, OutputT]` — generic async-first abstract base with typed generics
- `GlobalState` — dual-layer state (app-level messages + pydantic-ai message_history)
- `BaseSessionState` — extends GlobalState with session_id, serialize/deserialize for persistence
- `call_model()` / `call_model_stream()` / `stream_output()` / `stream_events()` — multi-turn + streaming
- `keep_recent_messages()` / `budget_tool_results()` — pure function history processors
- `ContextManager` — token-aware progressive compaction (summarize at 60%, truncate at 85%)
- `as_tool()` — wrap any BaseAgent as a pydantic-ai Tool (stateless per invocation)
- `CompoundTool` — agent→execute→update pattern with hook integration
- `resolve_model()` — lazy registry-based multi-provider routing (OpenAI, Anthropic, Google, OpenRouter)

### Orchestration
- `Pipeline` — sequential step execution with STOP/SKIP/RETRY error strategies
- `Parallel` — concurrent execution with merge strategies and timeout
- `Router` — rule-based and LLM-driven conditional routing with fallback
- `RefinementLoop` — iterative refinement with evaluator feedback and convergence detection
- `Step` protocol — unified interface for agents and pure async functions
- `AgentStep` / `FunctionStep` — concrete step implementations with auto-coercion

### MCP Integration
- `MCPServerManager` — manage connections to multiple MCP servers with auto-discovery
- `MCPConnection` — single server lifecycle (connect, list tools, call tools, disconnect)
- `MCPToolAdapter` — bridge MCP tool definitions → pydantic-ai Tool instances
- `create_orqest_server()` — expose Orqest as a FastMCP server (create_agent, run_agent, solve_goal, list_agents)
- Auto-discovery from `~/.claude.json`, `~/.claude/claude.json`, `~/.config/Claude/claude_desktop_config.json`
- Async context manager support (`async with MCPServerManager() as mgr`)

### Infrastructure
- `HookRunner` + `ToolHook` — fire-and-forget lifecycle hooks (before/after/error)
- 283 tests (all passing)
- 8 example notebooks tested with real LLMs (gpt-4.1)

## What's Next (Roadmap)

| Phase | What | Status |
|-------|------|--------|
| 1a. Orchestration | Pipeline, Parallel, Router, RefinementLoop | **DONE** |
| 1b. Core Uplift | HookRunner, BaseSessionState, CompoundTool | **DONE** |
| 2. Memory | MemoryStore protocol, SQLite + Supabase backends | **IN PROGRESS** |
| 3. Autonomy | AgentFactory, AgentSpec, MetaOrchestrator, ToolRegistry | Planned |
| 4. Observability | Tracing, event bus | Planned |
| 5. MCP Server | MCPServerManager + MCPToolAdapter + FastMCP server | **DONE** |
| 6. Resilience | Watchdog, diagnostic retry, resource quotas | Planned |

See `.claude/ROADMAP.md` for full details on each phase.

## Global Agents

This project has dedicated global agents in `~/.claude/skills/`:

| Agent | When to Use |
|-------|-------------|
| `/g-orchestrator` | **Primary agent for orqest work.** Design, build, or research mode. |
| `/g-specwright` | Spec-driven TDD before implementing features. |
| `/g-critic` | Adversarial read-only code review before merging. |
| `/g-auditor` | Audit plans for hidden assumptions before execution. |
| `/g-pragmatist` | Code quality audits (SOLID, DRY, YAGNI). |
| `/g-sre` | CI/CD setup (GitHub Actions, PyPI publishing). |
| `/g-chronicler` | Documentation, README, CHANGELOG, ADRs. |
| `/g-scout` | Research competing frameworks for roadmap decisions. |
| `/g-strategist` | Architecture brainstorming with Gemini. |

### Recommended Workflow

1. `/g-orchestrator` (design) → 2. `/g-auditor` (assumptions) → 3. `/g-specwright` (spec+TDD) → 4. `/g-critic` (review) → 5. `/g-chronicler` (docs)

## References

- `.claude/PRINCIPLES.md` — Pragmatic Programmer-based coding standards
- `.claude/ARCHITECTURE.md` — module dependency map, design decisions, extension points
- `.claude/ROADMAP.md` — full phased roadmap with implementation details
- `docs/` — user-facing MkDocs documentation
- `CHANGELOG.md` — version history
