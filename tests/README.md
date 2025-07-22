# Orqest Tests

This directory contains tests for the Orqest framework. The tests are organized by module and use pytest for test execution.

## Test Structure

The tests are organized into the following directories:

- `agents/`: Tests for agent implementations
  - `test_planner.py`: Tests for the PlannerAgent
  - `test_orchestrator.py`: Tests for the OrchestratorAgent
- `errors/`: Tests for error handling
  - `test_error_classes.py`: Tests for error classes and utilities
  - `test_agent_error_handling.py`: Tests for error handling in agents
- `conftest.py`: Common test fixtures and configuration

## Running Tests

To run all tests:

```bash
python -m pytest tests/
```

To run tests for a specific module:

```bash
python -m pytest tests/agents/
python -m pytest tests/errors/
```

To run a specific test file:

```bash
python -m pytest tests/agents/test_planner.py
```

## Test Fixtures

Common test fixtures are defined in `conftest.py` and include:

- `global_state`: A GlobalState instance with a user message
- `planner_agent`: A PlannerAgent instance
- `orchestrator_agent`: An OrchestratorAgent instance

These fixtures can be used in any test by adding them as parameters to the test function.

## Async Tests

Many tests in Orqest are asynchronous due to the async nature of the agent operations. These tests use the `pytest-asyncio` plugin and are marked with the `@pytest.mark.asyncio` decorator.

## Mocking

The tests use `unittest.mock` to mock dependencies and isolate the components being tested. This allows for testing error handling and edge cases without requiring actual LLM API calls.

## Adding New Tests

When adding new tests:

1. Follow the existing directory structure
2. Use pytest fixtures for common setup
3. Use the `@pytest.mark.asyncio` decorator for async tests
4. Use descriptive test names that explain what is being tested
5. Include assertions that verify the expected behavior