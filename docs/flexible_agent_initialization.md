# Flexible Agent Initialization Design

## Current Limitations

The current implementation of specialized agents in Orqest has several limitations:

1. **Hardcoded Configuration**: Agents have hardcoded values for agent_name, system_prompt, output_type, retries, and tools.
2. **No Parameter Passing**: The __init__ methods don't accept parameters that could be passed to the BaseAgent constructor.
3. **Nested Rigidity**: Agents that create sub-agents (like OrchestratorAgent creating a PlannerAgent) have nested hardcoded configurations.
4. **Limited Reusability**: Users can't create multiple instances of the same agent class with different configurations.
5. **Maintenance Challenges**: When BaseAgent is updated, all specialized agent classes need to be updated.

## Proposed Design

To address these limitations, we propose the following design changes:

### 1. Parameterized Initialization

Modify the __init__ methods of specialized agents to accept parameters for all BaseAgent configuration options:

```python
def __init__(
    self,
    agent_name: str = "default_name",
    system_prompt: Optional[str] = None,
    output_type: Optional[Type] = None,
    retries: int = 3,
    deps_type: Optional[Type[BaseModel]] = None,
    tools: Optional[List[Callable]] = None,
    # Additional agent-specific parameters
    ...
):
    # Use provided values or defaults
    _agent_name = agent_name or "default_name"
    _system_prompt = system_prompt or self._build_default_system_prompt()
    _output_type = output_type or (GlobalState | NoValidResponse)
    _tools = tools or [self._default_tool]
    
    super().__init__(
        agent_name=_agent_name,
        system_prompt=_system_prompt,
        output_type=_output_type,
        retries=retries,
        deps_type=deps_type,
        tools=_tools
    )
```

### 2. Configurable Sub-agents

For agents that create sub-agents, allow passing custom sub-agent instances or configuration:

```python
def __init__(
    self,
    # BaseAgent parameters
    ...,
    # Sub-agent parameters
    planner_agent: Optional[PlannerAgent] = None,
    planner_config: Optional[Dict[str, Any]] = None
):
    # Initialize BaseAgent
    super().__init__(...)
    
    # Initialize sub-agent
    if planner_agent:
        self.planner_agent = planner_agent
    else:
        planner_config = planner_config or {}
        self.planner_agent = PlannerAgent(**planner_config)
```

### 3. Example Usage

The new design would allow users to customize agents in various ways:

```python
# Basic usage with defaults
orchestrator = OrchestratorAgent()

# Customized orchestrator
orchestrator = OrchestratorAgent(
    agent_name="custom_orchestrator",
    system_prompt="Custom system prompt...",
    retries=5
)

# Customized orchestrator with custom planner
planner = PlannerAgent(
    agent_name="custom_planner",
    system_prompt="Custom planner prompt..."
)
orchestrator = OrchestratorAgent(
    agent_name="custom_orchestrator",
    planner_agent=planner
)

# Customized orchestrator with planner configuration
orchestrator = OrchestratorAgent(
    agent_name="custom_orchestrator",
    planner_config={
        "agent_name": "configured_planner",
        "retries": 4
    }
)
```

## Benefits

This design provides several benefits:

1. **Flexibility**: Users can customize agent behavior without modifying the agent classes.
2. **Reusability**: The same agent class can be used to create multiple instances with different configurations.
3. **Maintainability**: When BaseAgent is updated, specialized agents automatically support the new features.
4. **Backward Compatibility**: Default values ensure existing code continues to work.
5. **Hierarchical Configuration**: Users can configure both parent and child agents in a hierarchical system.

## Implementation Plan

1. Modify PlannerAgent to accept configuration parameters
2. Modify OrchestratorAgent to accept configuration parameters and optional PlannerAgent
3. Update example code to demonstrate the new initialization pattern
4. Add documentation explaining the new initialization options