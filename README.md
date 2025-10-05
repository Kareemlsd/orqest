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
from examples.agents import GlobalState, OrchestratorAgent

# Create an orchestrator that can use other agents as tools
orchestrator = OrchestratorAgent()

async def process_query(query: str):
    """Process a user query through the orchestrator."""
    # Initialize state with user query
    state = GlobalState()
    state.add_message("user", query)
    
    # The orchestrator will automatically use specialized agents when needed
    result = await orchestrator.run(state)
    
    return result

async def main():
    """Main function demonstrating the framework."""
    query = "I need to plan a birthday party for a chocolate lover. Can you help?"
    result = await process_query(query)
    
    # Display the results
    print("Assistant response:", result.get_latest_assistant_message())
    if hasattr(result, 'plan') and result.plan:
        print("\nGenerated plan:")
        for i, step in enumerate(result.plan, 1):
            print(f"{i}. {step}")

# Run the example
if __name__ == "__main__":
    asyncio.run(main())
```

**Note**: Orqest is built on asynchronous programming. All agent operations use `async/await` for optimal performance and concurrency.

## Key Features in Action

### 🔧 Agent Composition
```python
# Agents can use other agents as tools
orchestrator = OrchestratorAgent()  # Automatically includes PlannerAgent
```

### 🚀 Lifecycle Hooks & Middleware
```python
# Add custom logic at any point in execution
agent.add_hook(HookPoint.PRE_RUN, validate_input)
agent.use_middleware(LoggingMiddleware())
```

### ⚡ Robust Error Handling
```python
# Structured error management with context
from orqest.errors import AgentError, ErrorSeverity
```

### 📊 Structured State Management
```python
# Type-safe state with Pydantic models
state = GlobalState()
state.add_message("user", "Your message")
latest = state.get_latest_user_message()
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

## Getting Started

### Installation

Before installing Orqest, ensure you have Python 3.12 or higher. Then install using pip:

```bash
pip install orqest
```

Or clone and install from source for development:

```bash
git clone https://github.com/Kareemlsd/orqest.git
cd orqest
pip install -e .
```

### Configuration

Before using Orqest, configure your environment variables. Create a `.env` file in your project root:

```bash
# Required for LLM operations
LLM_API_KEY=your_openai_api_key_here
LLM_MODEL=gpt-3.5-turbo

# Optional: for embeddings
EMBEDDING_API_KEY=your_embedding_api_key_here
EMBEDDING_MODEL=text-embedding-ada-002
```

Alternatively, set environment variables directly:

```bash
export LLM_API_KEY=your_openai_api_key_here
export LLM_MODEL=gpt-3.5-turbo
```

### Quick Start with Examples

To get started quickly, run one of the included examples:

```bash
# Set up your environment
export LLM_API_KEY=your_openai_api_key
export LLM_MODEL=gpt-3.5-turbo

# Run the lifecycle hooks example
python examples/lifecycle_hooks_example.py
```

### Creating Custom Agents

Create your first agent with this streamlined implementation:

```python
import asyncio
from orqest.agents import BaseAgent, GlobalState, NoValidResponse
from typing import Union

class SimpleAgent(BaseAgent[GlobalState]):
    """A simple agent that responds to user messages."""
    
    def __init__(self):
        super().__init__(
            agent_name="simple_agent",
            system_prompt="You are a helpful assistant that provides concise, accurate responses.",
            output_type=Union[GlobalState, NoValidResponse],
            retries=2
        )
    
    async def _run_implementation(self, state: GlobalState, **kwargs) -> GlobalState:
        """Run the agent's main logic."""
        user_message = state.get_latest_user_message()
        if not user_message:
            state.add_message("assistant", "I didn't receive any message to respond to.")
            return state
        
        # Execute the agent with pydantic-ai
        response = await self.agent.run(user_message, deps=state, **kwargs)
        
        # Process the response
        return await self._process_response_implementation(response, state, **kwargs)
        
    async def _process_response_implementation(self, response, state: GlobalState, **kwargs) -> GlobalState:
        """Process the agent's response and update state."""
        if hasattr(response, 'data') and response.data:
            # Convert response to string and add to state
            response_text = str(response.data)
            state.add_message("assistant", response_text)
        else:
            state.add_message("assistant", "I apologize, but I couldn't generate a proper response.")
        
        return state

# Usage example
async def main():
    """Example usage of the SimpleAgent."""
    # Create the agent
    agent = SimpleAgent()
    
    # Create state and add a user message
    state = GlobalState()
    state.add_message("user", "Hello! Can you help me understand what Orqest is?")
    
    # Run the agent
    result = await agent.run(state)
    
    # Print the conversation
    print("Conversation:")
    print("-" * 40)
    for message in result.messages:
        role = message['role'].title()
        content = message['content']
        print(f"{role}: {content}")
        print()

if __name__ == "__main__":
    asyncio.run(main())
```

### Using Agent Composition

For complex workflows, use the agent composition pattern:

```python
import asyncio
from examples.agents import GlobalState, OrchestratorAgent

async def main():
    # Create an orchestrator that manages other agents
    orchestrator = OrchestratorAgent()
    
    # Initialize state with user query
    state = GlobalState()
    state.add_message("user", "Help me plan a project timeline")
    
    # Run the orchestrator
    result = await orchestrator.run(state)
    
    # The orchestrator automatically uses specialized agents as needed
    print("Response:", result.get_latest_assistant_message())
    if result.plan:
        print("\nGenerated plan:")
        for i, step in enumerate(result.plan, 1):
            print(f"{i}. {step}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Documentation & Resources

Explore our comprehensive resources to master Orqest:

### Core Documentation
- **[Examples Directory](examples/)**: Working examples demonstrating key concepts
- **[Tutorials](docs/tutorials/)**: Step-by-step Jupyter notebooks covering framework fundamentals
- **[Error Handling Guide](orqest/errors/README.md)**: Comprehensive error management patterns

### Key Concepts
1. **Agent Development**: Extend the `BaseAgent` class to create specialized agents
2. **State Management**: Use structured Pydantic models for type-safe state handling
3. **Agent Composition**: Leverage the "Agent as Tools" pattern for hierarchical workflows
4. **Lifecycle Hooks**: Inject custom logic at any point in an agent's execution
5. **Error Handling**: Implement robust error management with detailed context
6. **Asynchronous Processing**: Build high-performance systems with native asyncio support

### Example Usage Patterns
- **Simple Agents**: Single-purpose agents for specific tasks
- **Orchestrator Agents**: Multi-agent coordination and workflow management
- **Flexible Composition**: Dynamic agent graphs that adapt to requirements
- **Error Recovery**: Graceful handling of failures and edge cases

## Troubleshooting

### Common Issues and Solutions

**ImportError: No module named 'orqest'**
```bash
pip install -e .  # If working from source
# or
pip install orqest  # For stable release
```

**Missing Environment Variables**
```bash
# Ensure your .env file contains:
LLM_API_KEY=your_openai_api_key
LLM_MODEL=gpt-3.5-turbo
```

**Agent Not Responding**
- Verify your API key is valid and has sufficient credits
- Check that the LLM_MODEL is supported by your API provider
- Ensure your network connection allows API calls

**State Management Issues**
- Always use the GlobalState class for state management
- Remember to call `state.add_message()` to add messages to conversation history
- Use `state.get_latest_user_message()` to retrieve the most recent user input

**Example Not Working**
```bash
# Make sure you're in the correct directory
cd orqest

# Set environment variables
export LLM_API_KEY=your_key_here
export LLM_MODEL=gpt-3.5-turbo

# Run the example
python examples/lifecycle_hooks_example.py
```

## Community & Collaboration

Orqest is under active development by a dedicated team committed to advancing the state of AI agent orchestration. We welcome professional collaboration and contributions.

- **Contribute**: Submit pull requests or propose enhancements via our GitHub repository
- **Engage**: Participate in technical discussions and knowledge sharing
- **Implement**: Explore our reference implementations and case studies

## License

Orqest is enterprise-ready open-source software licensed under the [MIT license](LICENSE).