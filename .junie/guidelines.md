# Orqest Project Guidelines

## Project Overview

Orqest is a scalable framework for building advanced agentic workflows. It provides a structured approach to creating and managing complex agent-based systems by wrapping around the pydantic-ai library. The framework enables developers to:

- Create modular, reusable agents with a consistent interface
- Compose agents hierarchically, where agents can use other agents as tools
- Build dynamic orchestration patterns without hardcoded agent graphs
- Manage state and context across agent interactions

The core architecture is built around a few key concepts:
1. **BaseAgent**: An abstract class that provides the foundation for all agents in the system
2. **Specialized Agents**: Concrete implementations like PlannerAgent and OrchestratorAgent that extend BaseAgent
3. **Tools**: Functions that agents can use to perform specific tasks, including calling other agents
4. **State Management**: Using Pydantic models to define and validate state between agent interactions

## Project Structure

```
orqest/
├── agents/                  # Agent implementations
│   └── base_agent.py        # Abstract base class for all agents
├── io_utils/                # Input/output utilities (planned)
├── utils/                   # Utility functions
│   └── llm_model.py         # LLM model initialization
├── config.py                # Configuration management
└── __init__.py              # Package initialization
test_examples/               # Example implementations and tests
├── orchestrator_and_planner.py  # Example of agent composition
└── test_orchestrator_and_planner.py  # Tests for the example
```

### Key Components

1. **BaseAgent** (`orqest/agents/base_agent.py`):
   - Abstract base class for all agents
   - Provides common functionality for agent initialization, execution, and response processing
   - Manages LLM model initialization and agent configuration

2. **Configuration** (`orqest/config.py`):
   - Handles loading environment variables from a `.env` file
   - Provides configuration values for LLM and embedding models

3. **LLM Model** (`orqest/utils/llm_model.py`):
   - Initializes and returns the OpenAI model using pydantic-ai

4. **Example Implementation** (`test_examples/orchestrator_and_planner.py`):
   - Demonstrates how to create specialized agents (PlannerAgent and OrchestratorAgent)
   - Shows how to compose agents hierarchically using the "Agent as Tools" pattern
   - Provides a complete working example of the framework

## Development Guidelines

### Environment Setup

1. The project requires Python 3.12 or higher.
2. Create a `.env` file in the project root with the following variables:
   ```
   LLM_API_KEY=your_openai_api_key
   LLM_MODEL=gpt-3.5-turbo  # or another OpenAI model
   EMBEDDING_MODEL=all-MiniLM-L6-v2  # optional, defaults to this value
   EMBEDDING_API_KEY=your_embedding_api_key  # optional, defaults to LLM_API_KEY
   ```

### Code Style

The project uses ruff for linting and code formatting with the following guidelines:

1. Follow PEP 8 style guidelines for Python code.
2. Use docstrings for all modules, classes, and functions (Google style).
3. Maximum complexity for functions should be 10 (as configured in pyproject.toml).
4. Imports should be organized according to the isort configuration in pyproject.toml.
5. Type hints should be used for all function parameters and return values.

### Testing

1. Tests are written using pytest and pytest-asyncio.
2. Each agent implementation should have corresponding tests.
3. Tests should be organized in a way that mirrors the structure of the code being tested.
4. Run tests using:
   ```
   pytest test_examples/
   ```
5. For specific test files:
   ```
   python test_examples/test_orchestrator_and_planner.py
   ```

### Creating New Agents

When creating new agents:

1. Extend the `BaseAgent` class from `orqest.agents.base_agent`.
2. Implement the required abstract methods:
   - `run`: Execute the agent with a given state
   - `_process_agent_response`: Process the agent's response and update the state
3. Define a Pydantic model for the agent's state.
4. Use tools to extend the agent's capabilities.
5. Follow the example in `test_examples/orchestrator_and_planner.py`.

### Pull Request Guidelines

When submitting changes:

1. Ensure all tests pass.
2. Add tests for new functionality.
3. Update documentation as needed.
4. Follow the code style guidelines.
5. Keep changes focused and minimal.

## Junie Guidelines

When working with this project, Junie should:

1. **Run tests** to verify changes: Use pytest to run the tests in the test_examples directory.
2. **Write code using TDD**: Add features by following the 'Test Driven Development' concept.
3. **Check code style**: Ensure changes follow the project's code style guidelines using ruff.
4. **Maintain type hints**: All new code should include proper type hints.
5. **Document changes**: Update docstrings and comments for any modified code.
6. **Follow the architecture**: New components should align with the existing architecture patterns.
7. **Minimize dependencies**: Avoid adding new dependencies unless necessary.
8. **Verify environment compatibility**: Ensure changes work with the configured environment variables.

## Project Roadmap

Based on the current state of the codebase, the following areas are likely to be developed:

1. Implementation of specialized agents beyond the examples
2. Development of the io_utils module for input/output operations
3. Enhanced state management capabilities
4. Integration with additional LLM providers
5. More comprehensive testing infrastructure