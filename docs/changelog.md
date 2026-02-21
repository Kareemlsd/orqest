# Changelog

All notable changes to Orqest are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
