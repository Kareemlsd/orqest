# Orqest Error Handling

This module provides standardized error handling for the Orqest framework, including error categories, severity levels, and context information.

## Overview

The error handling system in Orqest is designed to provide:

1. **Standardized Error Format**: Consistent error structure across the framework
2. **Context-Rich Error Messages**: Detailed information about where and why errors occur
3. **Error Categorization**: Classification of errors by type and severity
4. **Structured Logging**: Formatted error messages for easier debugging

## Error Class Hierarchy

The error handling system is built around a hierarchy of error classes:

```
Exception
└── OrqestError
    ├── AgentError
    ├── LLMError
    ├── ValidationError
    └── ToolError
```

- **OrqestError**: Base class for all Orqest errors
- **AgentError**: Errors related to agent operations
- **LLMError**: Errors related to LLM operations
- **ValidationError**: Errors related to data validation
- **ToolError**: Errors related to tool execution

## Error Severity Levels

Errors can have different severity levels:

- **DEBUG**: Low severity, for debugging purposes
- **INFO**: Informational, not an error but noteworthy
- **WARNING**: Potential issue that doesn't prevent operation
- **ERROR**: Serious issue that prevents successful operation
- **CRITICAL**: Critical issue that requires immediate attention

## Error Categories

Errors are categorized by type:

- **AGENT**: Errors related to agent operations
- **LLM**: Errors related to LLM operations
- **VALIDATION**: Errors related to data validation
- **TOOL**: Errors related to tool execution
- **GENERAL**: General errors that don't fit other categories

## Error Context

Each error includes context information:

- **agent_name**: Name of the agent where the error occurred
- **operation**: Operation being performed when the error occurred
- **details**: Additional details about the error context
- **timestamp**: When the error occurred

## Usage Examples

### Creating and Raising Errors

```python
from orqest.errors import AgentError, ErrorSeverity, ErrorContext

# Create error context
context = ErrorContext(
    agent_name="my_agent",
    operation="run",
    details={"input": "user query", "state": "current state"}
)

# Create and raise an error
raise AgentError(
    message="Failed to process agent response",
    severity=ErrorSeverity.ERROR,
    context=context
)
```

### Handling Errors in Agents

```python
from orqest.errors import ErrorSeverity, ToolError

class MyAgent(BaseAgent):
    async def run(self, state):
        try:
            # Agent logic here
            response = await self.agent.run(prompt)
            return await self._process_agent_response(response, state)
        except Exception as e:
            # Create error details
            details = {
                "state": str(state),
                "error_type": type(e).__name__
            }
            
            # Return a NoValidResponse with error information
            return self._handle_agent_error(
                error=e,
                operation="run",
                severity=ErrorSeverity.ERROR,
                details=details
            )
```

### Using the Helper Methods in BaseAgent

BaseAgent provides helper methods for error handling:

- **_create_error_context**: Creates an ErrorContext instance with the agent's information
- **_handle_agent_error**: Handles an agent error and returns a NoValidResponse

```python
# Create error context
context = self._create_error_context(
    operation="run",
    details={"input": "user query"}
)

# Handle an error
response = self._handle_agent_error(
    error=exception,
    operation="run",
    severity=ErrorSeverity.ERROR,
    details={"input": "user query"}
)
```

### Formatting Error Messages

```python
from orqest.errors import format_error_message, AgentError

# Create an error
error = AgentError(
    message="Failed to process agent response",
    severity=ErrorSeverity.ERROR,
    context=context
)

# Format the error message
formatted_message = format_error_message(error)
logger.error(formatted_message)
```

## Best Practices

1. **Use Specific Error Types**: Use the most specific error type for the situation (AgentError, LLMError, etc.)
2. **Include Detailed Context**: Provide as much context as possible to help with debugging
3. **Set Appropriate Severity**: Use the appropriate severity level based on the impact of the error
4. **Handle Errors Gracefully**: Catch and handle errors at the appropriate level
5. **Log Errors Consistently**: Use the format_error_message function to ensure consistent error logging

## NoValidResponse

The `NoValidResponse` class is used to represent a state where an agent couldn't produce a valid response. It includes:

- **messages**: List of messages related to the error
- **error_message**: Detailed error message explaining what went wrong
- **error_type**: Type of error that occurred
- **agent_name**: Name of the agent that encountered the error
- **operation**: Operation being performed when the error occurred

This class is used as part of the output_type for agents to handle cases where the agent fails to produce a valid response.