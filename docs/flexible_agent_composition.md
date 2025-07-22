# Flexible Agent Composition in Orqest

This document explains the flexible agent composition approach in Orqest, which allows for dynamic agent composition without hardcoded references to specific agent types.

## Overview

Orqest's flexible agent composition approach enables developers to:

1. Use any agent as a tool for any other agent
2. Compose agents dynamically at runtime
3. Create reusable agent tools without modifying agent code
4. Maintain the "agents as tools" concept in a more flexible way

This approach removes the rigid coupling between agents (like the original OrchestratorAgent and PlannerAgent) and allows for more modular, reusable agent compositions.

## Key Components

### 1. Agent Tool Utility Function

The `create_agent_tool` function in `orqest/utils/agent_tools.py` is the core of the flexible agent composition approach. It wraps any agent as a tool function that can be used by other agents:

```python
from orqest.utils.agent_tools import create_agent_tool

# Create a tool function from an agent
tool_func = create_agent_tool(
    agent=my_agent,
    name="call_my_agent",
    description="Call my agent to process a query."
)

# Use the tool function in another agent
parent_agent = BaseAgent(
    agent_name="parent_agent",
    tools=[tool_func]
)
```

The `create_agent_tool` function handles:
- State passing between agents using RunContext
- Error handling and propagation
- Result extraction and formatting

### 2. FlexibleOrchestratorAgent

The `FlexibleOrchestratorAgent` in `examples/agents/flexible_orchestrator.py` demonstrates how to implement an agent that can use any other agent as a tool:

```python
from examples.agents.flexible_orchestrator import FlexibleOrchestratorAgent

# Create agents
planner_agent = PlannerAgent()
research_agent = ResearchAgent()

# Create a flexible orchestrator with subagents
orchestrator = FlexibleOrchestratorAgent(
    subagents={
        "plan_task": planner_agent,
        "research_topic": research_agent
    }
)
```

The `FlexibleOrchestratorAgent`:
- Accepts a dictionary of subagents in its constructor
- Uses `create_agent_tool` to wrap each subagent as a tool function
- Doesn't have hardcoded references to specific agent types
- Combines provided tools and subagent tools

## Benefits

### 1. Increased Flexibility

Developers can create any agent composition without modifying agent code. This allows for:
- Experimenting with different agent compositions
- Adapting agent compositions to different tasks
- Creating specialized agent compositions for specific domains

### 2. Improved Reusability

Agents can be reused in different contexts without modification:
- The same agent can be used as a tool by multiple parent agents
- Agents can be composed in different ways for different tasks
- Agent tools can be shared across projects

### 3. Better Maintainability

The flexible approach improves code maintainability:
- No hardcoded references to specific agent types
- Changes to one agent don't require changes to other agents
- New agent types can be added without modifying existing code

### 4. Enhanced Testability

The flexible approach makes testing easier:
- Agents can be tested in isolation
- Agent compositions can be tested with mock agents
- Different agent compositions can be tested without code changes

## Usage Examples

### Basic Usage

```python
from examples.agents.flexible_orchestrator import FlexibleOrchestratorAgent
from examples.agents import PlannerAgent, GlobalState

# Create a planner agent
planner = PlannerAgent()

# Create a flexible orchestrator with the planner as a subagent
orchestrator = FlexibleOrchestratorAgent(
    subagents={"plan_task": planner}
)

# Initialize state with a user query
state = GlobalState()
state.add_message("user", "What are the steps to bake a chocolate cake?")

# Run the orchestrator
result_state = await orchestrator.run(state)

# Print the plan
for step in result_state.plan:
    print(step)
```

### Using Multiple Agents

```python
from examples.agents.flexible_orchestrator import FlexibleOrchestratorAgent
from examples.agents import PlannerAgent, GlobalState
from your_agents import ResearchAgent, SummaryAgent

# Create different types of agents
planner = PlannerAgent()
researcher = ResearchAgent()
summarizer = SummaryAgent()

# Create a flexible orchestrator with multiple subagents
orchestrator = FlexibleOrchestratorAgent(
    subagents={
        "plan_task": planner,
        "research_topic": researcher,
        "summarize_text": summarizer
    }
)

# Initialize state with a user query
state = GlobalState()
state.add_message("user", "I need to bake a cake and learn about its history.")

# Run the orchestrator
result_state = await orchestrator.run(state)
```

### Creating Custom Agent Tools

```python
from orqest.utils.agent_tools import create_agent_tool
from orqest.agents.base_agent import BaseAgent
from your_agents import CustomAgent

# Create a custom agent
custom_agent = CustomAgent()

# Create a custom tool function with custom state modification and result extraction
def custom_state_modifier(query, state):
    # Custom logic to modify the state before passing it to the agent
    state.add_message("system", f"Processing query: {query}")
    state.context = {"query": query, "timestamp": time.time()}

def custom_result_extractor(result):
    # Custom logic to extract results from the agent's response
    if hasattr(result, "analysis"):
        return {"analysis": result.analysis, "confidence": result.confidence}
    return {"result": str(result)}

# Create a tool function with custom behavior
custom_tool = create_agent_tool(
    agent=custom_agent,
    name="analyze_data",
    description="Analyze data using the custom agent.",
    state_modifier=custom_state_modifier,
    result_extractor=custom_result_extractor
)

# Use the custom tool in another agent
parent_agent = BaseAgent(
    agent_name="parent_agent",
    tools=[custom_tool]
)
```

## Implementation Details

### State Passing

The flexible approach uses RunContext to pass state between agents:

1. The parent agent's state is passed to the tool function via RunContext
2. The tool function modifies the state as needed (e.g., adding the query as a user message)
3. The tool function runs the subagent with the modified state
4. The subagent updates the state and returns it
5. The tool function extracts the relevant information from the updated state and returns it to the parent agent

This approach ensures that state is properly shared between agents and that changes made by subagents are reflected in the parent agent's state.

### Error Handling

The flexible approach includes robust error handling:

1. Errors in subagents are caught and propagated to the parent agent
2. Error information is included in the tool function's return value
3. The parent agent can handle errors from subagents appropriately

This ensures that errors in subagents don't crash the parent agent and that error information is properly propagated.

## Conclusion

Orqest's flexible agent composition approach provides a powerful way to create dynamic, reusable agent compositions without hardcoded references to specific agent types. By using the `create_agent_tool` function and the `FlexibleOrchestratorAgent` pattern, developers can create complex agent systems that are more flexible, reusable, and maintainable than traditional approaches.

This approach maintains the "agents as tools" concept that is central to Orqest, while removing the rigid coupling between agents that can limit flexibility and reusability.