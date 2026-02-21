# Orqest — Agent Instructions

## What This Is

Orqest is a Python framework for building AI agents on top of pydantic-ai. It provides a generic base agent class, multi-provider model routing, and conversation state management. The goal is to grow it into a full multi-agent orchestration framework and publish it as open source.

**Current version:** 0.0.1 (early development)

## Project Structure

```
orqest/
├── __init__.py              # Re-exports OrqestConfig, load_config, get_default_config
├── config.py                # OrqestConfig dataclass + load_config() factory
├── agents/
│   ├── __init__.py          # Re-exports BaseAgent, GlobalState, keep_recent_messages
│   ├── base_agent.py        # BaseAgent[StateT, OutputT] + keep_recent_messages()
│   └── state.py             # GlobalState — shared conversation state
├── utils/
│   └── llm_model.py         # resolve_model() — mapping-based multi-provider routing
└── io_utils/
    └── load_sys_prompt.py   # load_sys_prompt() — finds and loads system prompt .txt files

tests/                       # Mirrors source layout
├── conftest.py              # Shared fixtures (OrqestConfig, TestModel)
├── test_config.py
├── agents/
│   ├── test_base_agent.py
│   └── test_state.py
├── utils/
│   └── test_llm_model.py
└── io_utils/
    └── test_load_sys_prompt.py

examples/                    # Numbered subfolders, progressively advanced
└── 01_basic_agent/          # Single agent with structured output
    └── basic_agent.ipynb
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

## Dev Commands

```bash
# Install in dev mode
pip install -e .

# Run tests
.venv/bin/python -m pytest tests/ -v

# Lint
ruff check orqest/

# Build
python -m build
```

## What Exists Today

- `OrqestConfig` frozen dataclass + `load_config()` / `get_default_config()` factories
- `BaseAgent[StateT, OutputT]` with explicit model param, tool/toolset registration, history processing
- `keep_recent_messages()` — pure function for history truncation with turn integrity repair
- `GlobalState` for conversation tracking with `get_latest_message(role)`
- `resolve_model()` — mapping-based multi-provider routing (OpenAI, Anthropic, Google, OpenRouter)
- `load_sys_prompt()` — system prompt file loader utility
- Test suite with 47 tests covering all modules

## What Does NOT Exist Yet

- Multi-agent orchestration / composition
- Workflow or pipeline primitives
- Agent-as-tool patterns
- Observability / tracing
- CI/CD

## References

- `.claude/PRINCIPLES.md` — development principles and coding standards (Pragmatic Programmer-based)
- `.claude/ARCHITECTURE.md` — detailed design decisions and module dependencies
- `.claude/ROADMAP.md` — planned features and priorities
