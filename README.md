# Orqest: Enterprise-Grade AI Agent Orchestration Framework

<p align="center">
  <em>Transform how you build, deploy, and scale AI agent systems</em>
</p>

## The Next Evolution in AI Orchestration

Orqest is an advanced framework for developing sophisticated AI agent systems with unparalleled flexibility and control. Whether implementing complex multi-agent workflows or streamlined single-agent applications, Orqest provides the robust architecture and comprehensive tooling required for production-grade AI systems.

**Elevate your AI development capabilities with a framework designed for the challenges of modern AI orchestration.**

## What Sets Orqest Apart

In the rapidly evolving landscape of AI agent frameworks, Orqest stands as a transformative solution that addresses the fundamental challenges of building complex, production-ready agent systems:

- **Hierarchical Agent Composition** - Unlike traditional frameworks that limit agent interactions to predefined patterns, Orqest enables true hierarchical composition where any agent can leverage other agents as tools, creating powerful emergent capabilities
- **Dynamic Execution Paths** - Orqest eliminates rigid, hardcoded agent graphs in favor of flexible, context-aware orchestration that adapts to changing requirements at runtime
- **Enterprise-Ready Architecture** - Built from the ground up with production use cases in mind, featuring comprehensive error handling, state management, and performance optimization
- **Unified Development Experience** - Provides a consistent interface across different agent types, significantly reducing the learning curve and development time

## Why Choose Orqest

- **Modular Agent Architecture** - Develop specialized agents that can be composed to address complex problems with unprecedented flexibility
- **Adaptive Workflow Orchestration** - Implement sophisticated workflows that dynamically adjust based on context and requirements
- **Comprehensive State Management** - Maintain coherent context across agent interactions with structured, type-safe state handling
- **Production-Optimized Design** - Deploy with confidence using robust error handling, lifecycle hooks, and asynchronous processing
- **Developer Productivity** - Accelerate development with clean, consistent interfaces and minimal boilerplate code

## Ideal For

- **AI Research Teams** - Accelerate experimentation with complex agent architectures while maintaining research-grade code quality
- **Enterprise AI Departments** - Implement production-ready agent systems that meet stringent reliability and scalability requirements
- **Product Development Organizations** - Reduce time-to-market for AI-powered features with a framework designed for collaboration and maintainability
- **System Integrators** - Deliver customized AI solutions that can adapt to evolving business requirements with minimal refactoring

## Implementation Example

Here's how easy it is to create a multi-agent workflow with Orqest:

```python
import asyncio
from examples.agents import GlobalState, OrchestratorAgent, PlannerAgent

# Create a planner agent
planner = PlannerAgent()

# Create an orchestrator that can use the planner
orchestrator = OrchestratorAgent()

# Process a user query through the orchestrator
async def process_query(query: str):
    # Initialize state with user query
    state = GlobalState()
    state.add_message("user", query)
    
    # The orchestrator will automatically use the planner when needed
    result = await orchestrator.run(state)
    
    return result

# Run the example
query = "I need to plan a birthday party for a chocolate lover. Can you help?"
result = asyncio.run(process_query(query))

# Display the results
print("Assistant response:", result.get_latest_assistant_message())
if result.plan:
    print("\nGenerated plan:")
    for i, step in enumerate(result.plan, 1):
        print(f"{i}. {step}")
```

## Core Capabilities

### Agent Composition Framework
Leverage a sophisticated composition model where agents can be assigned as tools to other agents, enabling dynamic orchestration without predefined interaction patterns. This architecture facilitates complex collaboration patterns that emerge naturally from your system design.

### Flexible Execution Architecture
Implement virtually any agent architecture required by your use case. From linear processing chains to complex directed graphs with feedback loops and conditional branching, Orqest provides the foundation for your specific implementation needs.

### Comprehensive Lifecycle Management
Integrate custom logic at any point in an agent's execution lifecycle through a powerful hooks system. Implement logging, performance monitoring, error handling, or domain-specific behaviors with precision and control.

### Enterprise-Grade Error Handling
Deploy with confidence using standardized error handling that includes severity classification, detailed context information, and configurable recovery strategies, significantly reducing debugging time and improving system reliability.

### Structured State Management
Maintain system coherence with a type-safe, structured approach to state management between agent interactions. This ensures consistent context propagation and eliminates an entire class of state-related errors common in complex agent systems.

### High-Performance Asynchronous Processing
Scale efficiently with native asyncio support, enabling concurrent operations and optimal resource utilization even under high load conditions.

## Getting Started

### Installation

```bash
pip install orqest
```

### Implementation Guide

Create your first agent with this streamlined implementation:

```python
from orqest.agents.base_agent import BaseAgent
from pydantic import BaseModel, Field
from typing import List, Dict, Any

# Define your state model
class SimpleState(BaseModel):
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    
    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        
    def get_latest_message(self):
        return self.messages[-1]["content"] if self.messages else ""

# Create your agent
class SimpleAgent(BaseAgent[SimpleState]):
    def __init__(self):
        super().__init__(
            agent_name="simple_agent",
            output_type=SimpleState,
            system_prompt="You are a helpful assistant."
        )
    
    async def _run_implementation(self, state: SimpleState, **kwargs) -> SimpleState:
        # Get the user's query
        query = state.get_latest_message()
        
        # Execute the agent
        response = await self.agent.run(query, deps=state, **kwargs)
        
        # Process the response
        return await self._process_response_implementation(response, state, **kwargs)
        
    async def _process_response_implementation(self, response, state: SimpleState, **kwargs) -> SimpleState:
        # Add the response to the state
        state.add_message("assistant", response.content)
        return state
```

## Documentation & Resources

Access our comprehensive documentation to maximize your implementation success:

1. **Framework Fundamentals**: Core concepts and architectural principles
2. **Agent Development Guide**: Designing and implementing specialized agents
3. **State Management Patterns**: Advanced techniques for context management
4. **Composition Strategies**: Hierarchical agent composition for complex workflows
5. **Lifecycle Management**: Leveraging hooks for custom processing logic
6. **Error Handling Protocols**: Implementing robust error management
7. **Orchestration Patterns**: Building flexible, adaptive agent systems

## Community & Collaboration

Orqest is under active development by a dedicated team committed to advancing the state of AI agent orchestration. We welcome professional collaboration and contributions.

- **Contribute**: Submit pull requests or propose enhancements via our GitHub repository
- **Engage**: Participate in technical discussions and knowledge sharing
- **Implement**: Explore our reference implementations and case studies

## License

Orqest is enterprise-ready open-source software licensed under the [MIT license](LICENSE).