# Orqest Examples

This directory contains example scripts that demonstrate how to use the Orqest framework.

## Available Examples

### orchestrator_example.py

This example demonstrates how to use the OrchestratorAgent and PlannerAgent together to create plans for user queries. It shows:

- How to create an OrchestratorAgent (which internally creates a PlannerAgent)
- How to initialize a GlobalState with a user query
- How to run the orchestrator and process the results
- How to handle errors and log results

### error_handling_example.py

This example demonstrates how to use the error handling system in Orqest. It shows:

- How to create and raise different error types (AgentError, ToolError)
- How to use error context and severity
- How to handle errors and return NoValidResponse
- How to process and log error information

### flexible_orchestrator_example.py

This example demonstrates the flexible agent composition approach in Orqest. It shows:

- How to create different types of agents (PlannerAgent, ResearchAgent, SummaryAgent)
- How to use the FlexibleOrchestratorAgent to compose agents dynamically
- How to pass any agent as a tool to another agent without hardcoded references
- How to run different agent compositions with the same code

## Running the Examples

Before running the examples, make sure you have:

1. Set up your environment variables in a `.env` file in the project root:
   ```
   LLM_API_KEY=your_openai_api_key
   LLM_MODEL=gpt-3.5-turbo  # or another OpenAI model
   ```

2. Installed the required dependencies:
   ```bash
   pip install -e .
   ```

Then you can run an example using:

```bash
python examples/orchestrator_example.py
```

## Creating Your Own Examples

You can use these examples as a starting point for creating your own agent implementations. Key points to remember:

1. Import the necessary components from the Orqest framework:
   ```python
   from orqest.agents.state import GlobalState
   from orqest.agents.base_agent import BaseAgent
   ```

2. Create your own agent by extending BaseAgent:
   ```python
   class MyAgent(BaseAgent[GlobalState]):
       # Implement your agent logic
   ```

3. Use the agent in your application:
   ```python
   async def run_my_agent():
       agent = MyAgent()
       state = GlobalState()
       state.add_message("user", "Your query here")
       result = await agent.run(state)
       return result
   ```

4. Run your async code:
   ```python
   if __name__ == "__main__":
       import asyncio
       asyncio.run(run_my_agent())
   ```

For more detailed examples, refer to the implementation of PlannerAgent and OrchestratorAgent in the `examples/agents/` directory.