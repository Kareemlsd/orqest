# Orqest Project Structure

This document provides an overview of the Orqest project structure after cleanup.

## Directory Structure

```
orqest/                      # Main package directory
├── agents/                  # Agent implementations
│   ├── base_agent.py        # Abstract base class for all agents
│   ├── state.py             # State models for agents
│   └── __init__.py          # Package initialization
├── errors/                  # Error handling
│   ├── error_format.py      # Error classes and formatting
│   ├── README.md            # Documentation for error handling
│   └── __init__.py          # Package initialization
├── io_utils/                # Input/output utilities (planned)
│   └── __init__.py          # Package initialization
├── utils/                   # Utility functions
│   ├── agent_tools.py       # Utilities for working with agents as tools
│   ├── llm_model.py         # LLM model initialization
│   └── __init__.py          # Package initialization
├── config.py                # Configuration management
└── __init__.py              # Package initialization

examples/                    # Example implementations
├── agents/                  # Example agent implementations
│   ├── flexible_orchestrator.py  # Flexible orchestrator agent
│   ├── orchestrator.py      # Orchestrator agent
│   ├── planner.py           # Planner agent
│   ├── state.py             # State models for example agents
│   └── __init__.py          # Package initialization
├── error_handling_example.py  # Example of error handling
├── flexible_orchestrator_example.py  # Example of flexible orchestrator
├── orchestrator_example.py  # Example of orchestrator and planner
├── README.md                # Documentation for examples
└── __init__.py              # Package initialization

tests/                       # Tests for the framework
├── agents/                  # Tests for agent implementations
│   ├── test_orchestrator.py # Tests for orchestrator agent
│   └── test_planner.py      # Tests for planner agent
├── errors/                  # Tests for error handling
│   ├── test_agent_error_handling.py  # Tests for agent error handling
│   └── test_error_classes.py  # Tests for error classes
├── utils/                   # Tests for utility functions (empty)
├── conftest.py              # Common test fixtures
└── README.md                # Documentation for tests

docs/                        # User-facing documentation
├── error_handling_superiority.md  # Documentation on error handling
├── flexible_agent_composition.md  # Documentation on flexible agent composition
└── implementation_summary.md  # Summary of implementation

design_docs/                 # Design documentation
├── flexible_agent_initialization.md  # Design for flexible agent initialization
└── flexible_agent_initialization_summary.md  # Summary of flexible agent initialization design
```

## Key Components

### Core Framework (orqest/)

1. **BaseAgent** (`orqest/agents/base_agent.py`):
   - Abstract base class for all agents
   - Provides common functionality for agent initialization, execution, and response processing
   - Manages LLM model initialization and agent configuration
   - Includes error handling utilities

2. **State Models** (`orqest/agents/state.py`):
   - Defines Pydantic models for agent state
   - Provides methods for managing messages and retrieving state information

3. **Error Handling** (`orqest/errors/`):
   - Provides standardized error handling for the framework
   - Includes error categories, severity levels, and context information
   - Offers utilities for formatting error messages

4. **Agent Tools** (`orqest/utils/agent_tools.py`):
   - Provides utilities for working with agents as tools
   - Enables flexible agent composition

5. **LLM Model** (`orqest/utils/llm_model.py`):
   - Initializes and returns the OpenAI model using pydantic-ai

6. **Configuration** (`orqest/config.py`):
   - Handles loading environment variables from a `.env` file
   - Provides configuration values for LLM and embedding models

### Examples (examples/)

1. **Example Agents** (`examples/agents/`):
   - Implementations of specialized agents that extend BaseAgent
   - Includes OrchestratorAgent, PlannerAgent, and FlexibleOrchestratorAgent
   - Demonstrates how to create custom agents

2. **Example Scripts**:
   - `orchestrator_example.py`: Demonstrates the use of OrchestratorAgent and PlannerAgent
   - `error_handling_example.py`: Demonstrates the error handling capabilities
   - `flexible_orchestrator_example.py`: Demonstrates flexible agent composition

### Tests (tests/)

1. **Agent Tests** (`tests/agents/`):
   - Tests for agent implementations
   - Verifies that agents work correctly

2. **Error Tests** (`tests/errors/`):
   - Tests for error handling
   - Verifies that errors are properly handled and propagated

### Documentation (docs/ and design_docs/)

1. **User Documentation** (`docs/`):
   - Documentation for users of the framework
   - Explains how to use the framework's features

2. **Design Documentation** (`design_docs/`):
   - Documentation of design decisions
   - Explains the rationale behind the framework's architecture

## File Organization

The project follows a modular organization with clear separation of concerns:

- Core framework code is in the `orqest/` directory
- Example implementations are in the `examples/` directory
- Tests are in the `tests/` directory
- Documentation is in the `docs/` and `design_docs/` directories

This organization makes it easy to:
- Find and understand the core framework code
- See examples of how to use the framework
- Run tests to verify the framework's functionality
- Access documentation to learn about the framework

## Development Workflow

When developing with Orqest:

1. Core framework changes should be made in the `orqest/` directory
2. Examples should be added to the `examples/` directory
3. Tests should be added to the `tests/` directory
4. Documentation should be updated in the `docs/` directory

For more detailed guidelines, see the `.junie/guidelines.md` file.