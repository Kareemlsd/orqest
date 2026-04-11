# Orqest — Agent Instructions

## What This Is

Orqest is a Python framework for building AI agents on top of pydantic-ai. It provides a generic base agent class, multi-provider model routing, conversation state management, and agent composition primitives. The goal is to grow it into a full multi-agent orchestration framework and publish it as open source.

**Current version:** 0.0.1 (early development)

## Project Structure

```
orqest/
├── __init__.py              # Re-exports OrqestConfig, load_config, get_default_config
├── config.py                # OrqestConfig dataclass + load_config() factory
├── agents/
│   ├── __init__.py          # Re-exports BaseAgent, GlobalState, as_tool, keep_recent_messages
│   ├── base_agent.py        # BaseAgent[StateT, OutputT] + call_model() + streaming + keep_recent_messages()
│   ├── state.py             # GlobalState — shared conversation state
│   └── tool_wrapper.py      # as_tool() — wrap a BaseAgent as a pydantic-ai Tool
├── utils/
│   └── llm_model.py         # resolve_model() — mapping-based multi-provider routing
└── io_utils/
    └── load_sys_prompt.py   # load_sys_prompt() — finds and loads system prompt .txt files

tests/                       # Mirrors source layout
├── conftest.py              # Shared fixtures (OrqestConfig, TestModel)
├── test_config.py
├── agents/
│   ├── test_base_agent.py
│   ├── test_state.py
│   └── test_tool_wrapper.py
├── utils/
│   └── test_llm_model.py
└── io_utils/
    └── test_load_sys_prompt.py

examples/                    # Numbered subfolders, progressively advanced
├── 01_basic_agent/          # Single agent with structured output + multi-turn
│   └── basic_agent.ipynb
├── 02_agent_as_tool/        # Agent-as-tool composition pattern
│   └── agent_as_tool.ipynb
└── 03_streaming/            # Streaming patterns + transport integration
    └── streaming.ipynb

docs/                        # MkDocs documentation site (mkdocs.yml at project root)
├── index.md                 # Landing page with quick start
├── getting-started.md       # Full walkthrough: install → multi-turn
├── concepts/
│   ├── agents.md            # BaseAgent deep dive
│   ├── state-and-history.md # GlobalState, message_history, keep_recent_messages
│   ├── agent-as-tool.md     # as_tool(), stateless vs stateful
│   └── streaming.md         # Streaming methods, transport integration
├── api/                     # Auto-generated from docstrings via mkdocstrings
│   ├── config.md
│   ├── agents.md
│   ├── utils.md
│   └── io-utils.md
└── changelog.md
```

## Key Conventions

- **Async-first**: All agent execution is async. Use `async/await` everywhere.
- **Pydantic models**: State and output types must be Pydantic BaseModel subclasses.
- **Generic typing**: Agents are `BaseAgent[StateT, OutputT]` — always specify both type params.
- **Explicit dependencies**: No import-time side effects. Functions take deps as arguments.
- **Model format**: `LLM_MODEL` uses `provider:model_id` format (e.g., `openai:gpt-4o`).
- **pydantic-ai**: The underlying agent framework. Don't reinvent what it already provides.
- **Python 3.12+**: Minimum version. Use modern Python features.
- **Build system**: setuptools via pyproject.toml. Dependencies managed there.
- **Linting**: ruff (configured in pyproject.toml).
- **Testing**: pytest + pytest-asyncio. Run with `.venv/bin/python -m pytest tests/ -v`.
- **Documentation**: MkDocs + Material + mkdocstrings. Update docs when adding/changing features.
- **Changelog**: Keep a Changelog format in CHANGELOG.md. Update the [Unreleased] section with each feature.

## Dev Commands

```bash
# Install in dev mode
pip install -e .

# Run tests
.venv/bin/python -m pytest tests/ -v

# Lint
ruff check orqest/

# Docs — serve locally with hot reload
uv run mkdocs serve

# Docs — build static site
uv run mkdocs build

# Build package
python -m build
```

## What Exists Today

- `OrqestConfig` frozen dataclass + `load_config()` / `get_default_config()` factories
- `BaseAgent[StateT, OutputT]` with explicit model param, tool/toolset registration, history processing
- `call_model()` — multi-turn conversation support with automatic history wiring
- `call_model_stream()` — async context manager for streaming with history wiring
- `stream_output()` — async generator yielding partial structured output as the LLM generates tokens
- `stream_events()` — async generator yielding all agent events including tool call/result visibility
- `keep_recent_messages()` — pure function for history truncation with turn integrity repair
- `GlobalState` for conversation tracking with `messages` (app-level) and `message_history` (pydantic-ai)
- `resolve_model()` — mapping-based multi-provider routing (OpenAI, Anthropic, Google, OpenRouter)
- `as_tool()` — wrap any BaseAgent as a pydantic-ai Tool for stateless orchestrator invocation
- `load_sys_prompt()` — system prompt file loader utility
- Documentation site with MkDocs Material (concepts, getting started, auto-generated API reference)
- Test suite with 66 tests covering all modules

## What Does NOT Exist Yet

- Sequential pipeline primitives
- Context scoping
- Observability / tracing
- CI/CD

## Global Agents

This project has a dedicated global agent and several supporting agents
installed in `~/.claude/skills/`. Use them:

| Agent | When to Use |
|-------|-------------|
| `/g-orchestrator` | **Primary agent for orqest work.** Design mode, build mode, or research mode. Knows the architecture, roadmap, and principles. |
| `/g-specwright` | Before implementing any new feature. Writes contract-based specs, generates failing tests, then implements. |
| `/g-critic` | Before merging PRs. Adversarial read-only review. |
| `/g-auditor` | Audit plans and designs for hidden assumptions before execution. |
| `/g-pragmatist` | Code quality audits against Pragmatic Programmer principles. |
| `/g-sre` | Setting up CI/CD (GitHub Actions, PyPI publishing). |
| `/g-chronicler` | Updating docs, README, CHANGELOG, ADRs after features ship. |
| `/g-scout` | Researching competing frameworks (LangGraph, CrewAI, etc.) for roadmap decisions. |
| `/g-strategist` | Trade-off analysis and system design brainstorming with Gemini. |

### Recommended Workflow for New Features

1. `/g-orchestrator` (design mode) — design the feature using orqest patterns
2. `/g-auditor` — audit the design for hidden assumptions before building
3. `/g-specwright` — write contract spec → failing tests → implementation
4. `/g-critic` — review the implementation against spec
5. `/g-chronicler` — update docs and CHANGELOG

## References

- `.claude/PRINCIPLES.md` — development principles and coding standards (Pragmatic Programmer-based)
- `.claude/ARCHITECTURE.md` — module dependency map, design decisions, extension points
- `.claude/ROADMAP.md` — planned features and priorities (3 phases)
- `docs/` — user-facing documentation (MkDocs source)
- `CHANGELOG.md` — version history (Keep a Changelog format)
