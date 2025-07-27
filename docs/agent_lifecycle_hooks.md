# Agent Lifecycle Hooks

This document describes the Agent Lifecycle Hooks feature for the Orqest framework.

## Overview

Agent Lifecycle Hooks provide a way to inject custom logic at different points in an agent's lifecycle without modifying the core code. This enables developers to:

- Add pre/post-execution hooks for custom logic
- Implement middleware support for cross-cutting concerns
- Create an event system for agent lifecycle events

## Design

The Agent Lifecycle Hooks feature consists of three main components:

1. **Hook Points**: Specific points in the agent's lifecycle where custom logic can be injected
2. **Hook Registry**: A mechanism for registering hooks to be executed at specific hook points
3. **Hook Execution**: Logic for executing hooks at the appropriate times

### Hook Points

The following hook points are defined:

- `pre_run`: Executed before the agent's `run` method is called
- `post_run`: Executed after the agent's `run` method is called
- `pre_process_response`: Executed before the agent's `_process_agent_response` method is called
- `post_process_response`: Executed after the agent's `_process_agent_response` method is called
- `on_error`: Executed when an error occurs during the agent's execution

### Hook Registry

Hooks are registered using a decorator pattern or by directly adding them to the agent's hook registry. Each hook is associated with a specific hook point and can be given a priority to control the order of execution.

### Hook Execution

Hooks are executed in priority order at each hook point. Each hook can:

- Modify the state or other parameters
- Perform side effects (e.g., logging)
- Prevent further execution by raising an exception

## Implementation

The implementation will:

1. Add a hook registry to the BaseAgent class
2. Add methods for registering hooks
3. Modify the BaseAgent class to execute hooks at the appropriate hook points
4. Add helper methods for common hook patterns

## Usage Examples

### Adding a Pre-Run Hook

```python
from orqest.agents.base_agent import BaseAgent, hook

class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(...)
        
        # Register a pre-run hook
        self.add_hook('pre_run', self.log_run_start)
        
    async def log_run_start(self, state, **kwargs):
        print(f"Starting agent run with state: {state}")
        return state
```

### Using the Decorator Pattern

```python
from orqest.agents.base_agent import BaseAgent, hook

class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(...)
        
    @hook('pre_run')
    async def log_run_start(self, state, **kwargs):
        print(f"Starting agent run with state: {state}")
        return state
```

### Implementing Middleware

```python
from orqest.agents.base_agent import BaseAgent, Middleware

# Define middleware
class LoggingMiddleware(Middleware):
    async def pre_run(self, state, **kwargs):
        print(f"Starting agent run with state: {state}")
        return state
        
    async def post_run(self, state, result, **kwargs):
        print(f"Finished agent run with result: {result}")
        return result

# Use middleware
agent = MyAgent()
agent.use_middleware(LoggingMiddleware())
```

## Benefits

1. **Extensibility**: Allows developers to extend agent behavior without modifying core code
2. **Separation of Concerns**: Keeps core agent logic separate from cross-cutting concerns
3. **Reusability**: Enables the creation of reusable hooks and middleware
4. **Testability**: Makes it easier to test agent behavior by injecting mock hooks