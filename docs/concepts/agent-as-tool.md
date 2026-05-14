# Agent as Tool

The agent-as-tool pattern lets an orchestrating agent call specialized agents on demand. Each tool invocation is **stateless** — a fresh state is created, the query is passed in, and the structured output is returned.

## The Pattern

Instead of giving every agent access to the full conversation, you create focused agents that do one thing well and wrap them as tools for an orchestrator:

```
User → Orchestrator Agent
            ├── summarizer tool (wraps SummaryAgent)
            ├── translator tool (wraps TranslationAgent)
            └── analyst tool (wraps AnalystAgent)
```

The orchestrator's LLM decides which tool to call based on the user's request.

## Using `as_tool()`

```python
from orqest.agents import as_tool

# Create specialized agents
summarizer = SummaryAgent(model="openai:gpt-4.1", api_key="sk-...")
translator = TranslationAgent(model="openai:gpt-4.1", api_key="sk-...")

# Wrap as tools — one line each
summary_tool = as_tool(
    summarizer,
    description="Summarize a piece of text. Returns a concise summary and key points.",
)

translation_tool = as_tool(
    translator,
    description="Translate text to a target language.",
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent` | `BaseAgent` | required | The agent to wrap |
| `name` | `str \| None` | `None` | Tool name visible to the LLM (defaults to `agent.agent_name`) |
| `description` | `str` | required | Tool description — tells the LLM when to use this tool |

## Under the Hood

Each time the orchestrator's LLM calls the tool, `as_tool()` does this:

```python
state = GlobalState()           # fresh state — no history
state.add_message("user", query)
output = await agent.run(state) # runs _run_implementation → call_model
return output.model_dump_json() # structured output as JSON string
```

The orchestrator receives the JSON string and can use the structured data in its response.

## Full Example

```python
from pydantic_ai import Agent
from orqest import load_config
from orqest.agents import as_tool
from orqest.utils.llm_model import resolve_model

config = load_config()

# Specialized agents (defined elsewhere)
summarizer = SummaryAgent(model=config.llm_model, api_key=config.llm_api_key)
translator = TranslationAgent(model=config.llm_model, api_key=config.llm_api_key)

# Wrap as tools
summary_tool = as_tool(summarizer, description="Summarize text.")
translation_tool = as_tool(translator, description="Translate text.")

# Create orchestrator with the tools
orchestrator = Agent(
    model=resolve_model(config.llm_model, api_key=config.llm_api_key),
    system_prompt="Use the available tools to help the user.",
    tools=[summary_tool, translation_tool],
)

# Run — the orchestrator decides which tool to call
result = await orchestrator.run("Summarize this article about quantum computing...")
print(result.output)
```

## Stateful vs. Stateless

The same agent class works in both patterns — the invocation context determines behavior:

| | Multi-turn (direct) | Agent as Tool |
|---|---|---|
| **State** | Shared `GlobalState` across turns | Fresh `GlobalState` per call |
| **History** | Accumulates via `call_model()` | Always empty |
| **Use case** | Conversational agent | Focused, one-shot specialist |
| **Invocation** | `await agent.run(state)` | Called by orchestrator via tool |

An agent using `self.call_model()` in its `_run_implementation()` works in both contexts:

- When called directly with a persistent state, history accumulates across turns
- When called via `as_tool()`, each invocation gets a fresh state so history is always empty
