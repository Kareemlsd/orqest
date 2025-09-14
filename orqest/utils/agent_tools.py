"""Utility functions for working with agents as tools.

This module provides utility functions for working with agents as tools,
including functions to wrap agents as tools for other agents.
"""
import logging
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union, Awaitable

from pydantic import BaseModel
from pydantic_ai import RunContext

from orqest.agents import BaseAgent, NoValidResponse

logger = logging.getLogger(__name__)

# Type variable for the state
StateT = TypeVar("StateT", bound=BaseModel)

def create_agent_tool(
    agent: BaseAgent,
    name: Optional[str] = None,
    description: Optional[str] = None,
    state_modifier: Optional[Callable[[Any, StateT], None]] = None,
    result_extractor: Optional[Callable[[Any], Dict[str, Any]]] = None
) -> Callable[[RunContext[StateT], str], Awaitable[Dict[str, Any]]]:
    """Create a tool function that wraps an agent.
    
    This function creates a tool function that can be used to call an agent
    from another agent. The tool function takes a RunContext and a query string,
    and returns a dictionary with the result of running the agent.
    
    Args:
        agent: The agent to wrap as a tool.
        name: Optional name for the tool. If not provided, the agent's name will be used.
        description: Optional description for the tool. If not provided, a default description will be used.
        state_modifier: Optional function to modify the state before passing it to the agent.
            The function should take the query string and the state, and modify the state in place.
            If not provided, a default modifier will be used that adds the query as a user message.
        result_extractor: Optional function to extract the result from the agent's response.
            The function should take the agent's response and return a dictionary.
            If not provided, a default extractor will be used that returns the agent's state as a dictionary.
    
    Returns:
        A tool function that can be used to call the agent from another agent.
    """
    tool_name = name or f"call_{agent.agent_name}"
    tool_description = description or f"Call the {agent.agent_name} to process a query."
    
    # Default state modifier adds the query as a user message
    def default_state_modifier(query: str, state: StateT) -> None:
        if hasattr(state, "add_message") and callable(getattr(state, "add_message")):
            state.add_message("user", query)
        elif hasattr(state, "messages") and isinstance(state.messages, list):
            state.messages.append({"role": "user", "content": query})
    
    # Use the provided state modifier or the default one
    modifier = state_modifier or default_state_modifier
    
    # Default result extractor returns the agent's state as a dictionary
    def default_result_extractor(result: Any) -> Dict[str, Any]:
        if isinstance(result, NoValidResponse):
            # If the agent returned an error, return it as a dictionary
            return {
                "error": True,
                "error_message": result.error_message,
                "error_type": result.error_type,
                "agent_name": result.agent_name,
                "operation": result.operation
            }
        elif isinstance(result, BaseModel):
            # If the agent returned a state, convert it to a dictionary
            result_dict = {}
            for field_name, field_value in result:
                # Only include fields that are lists, strings, or dictionaries
                if isinstance(field_value, (list, str, dict)):
                    result_dict[field_name] = field_value
            return result_dict
        else:
            # If the agent returned something else, return it as is
            return {"result": result}
    
    # Use the provided result extractor or the default one
    extractor = result_extractor or default_result_extractor
    
    # Create the tool function
    async def tool_function(ctx: RunContext[StateT], query: str) -> Dict[str, Any]:
        """Call the agent to process a query.
        
        Args:
            ctx: The run context containing the state.
            query: The query to process.
            
        Returns:
            A dictionary with the result of running the agent.
        """
        try:
            # Get the state from the context
            state = ctx.deps
            
            # Modify the state with the query
            modifier(query, state)
            
            # Run the agent with the state
            result = await agent.run(state)
            
            # Extract and return the result
            return extractor(result)
            
        except Exception as e:
            # Log the error
            logger.error(f"Error calling {agent.agent_name}: {str(e)}")
            
            # Return an error dictionary
            return {
                "error": True,
                "error_message": str(e),
                "error_type": type(e).__name__,
                "agent_name": agent.agent_name
            }
    
    # Set the name and description of the tool function
    tool_function.__name__ = tool_name
    tool_function.__doc__ = tool_description
    
    return tool_function