"""Flexible orchestrator agent implementation.

This module contains an implementation of a flexible orchestrator agent using the Orqest framework.
It demonstrates how to create an agent that can use any other agent as a tool without hardcoded references.
"""
import logging
from typing import Any, Dict, List, Optional, Type, Union, Callable

from pydantic import BaseModel
from pydantic_ai import RunContext

from orqest.agents.base_agent import BaseAgent, NoValidResponse
from orqest.errors import ErrorSeverity, ErrorContext, ToolError
from orqest.utils.agent_tools import create_agent_tool

from examples.agents.state import GlobalState

logger = logging.getLogger(__name__)

class FlexibleOrchestratorAgent(BaseAgent[GlobalState]):
    """Flexible orchestrator agent created using the base agent from Orqest.
    
    This agent is responsible for orchestrating the execution of tasks by using
    other agents as tools. Unlike the original OrchestratorAgent, this agent
    doesn't have hardcoded references to specific agent types and can use any
    agent as a tool.
    """

    def __init__(
        self,
        agent_name: str = "flexible_orchestrator",
        system_prompt: Optional[str] = None,
        output_type: Optional[Type] = None,
        retries: int = 2,
        deps_type: Optional[Type[BaseModel]] = None,
        tools: Optional[List[Any]] = None,
        subagents: Optional[Dict[str, BaseAgent]] = None,
    ):
        """Initialize the flexible orchestrator agent.
        
        Args:
            agent_name: Name of the agent for logging and identification.
            system_prompt: The system prompt that defines the agent's behavior.
            output_type: The type of the output state.
            retries: Number of retries for failed agent executions.
            deps_type: Optional type for RunContext dependencies.
            tools: List of tools that the agent can use.
            subagents: Dictionary of subagents to use as tools, where the key is the tool name
                and the value is the agent instance.
        """
        # Set default values if not provided
        _system_prompt = system_prompt or self._build_system_prompt()
        _output_type = output_type or (GlobalState | NoValidResponse)
        
        # Create tools from subagents if provided
        subagent_tools = []
        if subagents:
            for name, agent in subagents.items():
                # Create a tool function for each subagent
                tool_func = create_agent_tool(
                    agent=agent,
                    name=name,
                    description=f"Call the {agent.agent_name} to process a query."
                )
                subagent_tools.append(tool_func)
        
        # Combine provided tools and subagent tools
        _tools = (tools or []) + subagent_tools
        
        # If no tools are provided, add a default tool that returns a message
        if not _tools:
            _tools = [self._default_tool]
        
        super().__init__(
            agent_name=agent_name,
            output_type=_output_type,
            system_prompt=_system_prompt,
            retries=retries,
            deps_type=deps_type or GlobalState,
            tools=_tools
        )
        
        # Store the subagents for reference
        self.subagents = subagents or {}

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the orchestrator agent.
        
        Returns:
            The system prompt string.
        """
        return """
            You are a flexible orchestrator agent. Your goal is to orchestrate the execution of tasks
            by using other agents as tools. You can call any of the available tools to help you
            complete the task.
            
            Your role is to:
            1. Analyze the user's request and determine what tools are needed.
            2. Call the appropriate tools to complete the task.
            3. Integrate the results from different tools into a coherent response.
            
            Use the tools strategically based on the current workflow state and user needs.
            """

    async def _default_tool(self, ctx: RunContext[GlobalState], query: str) -> Dict[str, Any]:
        """Default tool that returns a message.
        
        This tool is used when no other tools are provided.
        
        Args:
            ctx: The run context containing the global state.
            query: The query to process.
            
        Returns:
            A dictionary with a message.
        """
        return {
            "message": "No tools are available. Please add some tools to the orchestrator agent."
        }

    async def _run_implementation(self, state: GlobalState, **kwargs) -> GlobalState:
        """Run the orchestrator agent to manage the workflow.
        
        Args:
            state: The current state of the conversation.
            **kwargs: Additional keyword arguments to pass to the agent.
            
        Returns:
            Updated state after the agent has processed it.
        """
        try:
            # Analyze current state and determine next steps
            prompt = f"""
            Current workflow state: {state.plan}
            Current messages: {state.get_latest_user_message()}
            
            Please analyze the current workflow state and determine the next steps.
            Consider what information is missing and what tools are available.
            """

            # Log the operation
            logger.info(f"Running {self.agent_name} with prompt: {prompt[:100]}...")

            # Execute the agent
            response = await self.agent.run(prompt, deps=state, message_history=state.chat_history, **kwargs)
            state.chat_history.extend(response.all_messages())

            # Process the response
            return await self._process_response_implementation(response, state, **kwargs)
            
        except Exception as e:
            # Handle the error using the standardized error handling
            logger.error(f"Error running {self.agent_name}: {str(e)}")
            
            # Create error details
            details = {
                "user_message": state.get_latest_user_message() if hasattr(state, 'get_latest_user_message') else None,
                "state_messages_count": len(state.messages) if hasattr(state, 'messages') else 0,
                "state_plan_count": len(state.plan) if hasattr(state, 'plan') else 0
            }
            
            # Return a NoValidResponse with error information
            return self._handle_agent_error(
                error=e,
                operation="_run_implementation",
                severity=ErrorSeverity.ERROR,
                details=details
            )
        
    async def _process_response_implementation(self, response, state: GlobalState, **kwargs) -> GlobalState:
        """Process the agent response and update the state.
        
        Args:
            response: The response from the agent.
            state: The current state of the agent.
            **kwargs: Additional keyword arguments.
            
        Returns:
            Updated state after processing the response.
        """
        try:
            # Check if the response is valid
            if hasattr(response, "output") and response.output:
                # Extract plan from the response if available
                if hasattr(response.output, "plan") and response.output.plan:
                    state.plan = response.output.plan
                
                # Add the assistant's response to the messages
                content = response.content if hasattr(response, "content") else str(response.output)
                state.add_message("assistant", content)
                
                # Log successful processing
                logger.info(f"Successfully processed response for {self.agent_name}")
                
                return state
            else:
                # Handle invalid response with standardized error handling
                logger.warning(f"Received invalid response from {self.agent_name}")
                
                # Create error details
                details = {
                    "response_type": type(response).__name__,
                    "has_output": hasattr(response, "output"),
                    "has_content": hasattr(response, "content"),
                }
                
                # Create a more informative error message
                error_msg = "Invalid response format: The agent response did not contain valid output"
                
                # Create an error and return a NoValidResponse
                error = ValueError(error_msg)
                invalid_response = self._handle_agent_error(
                    error=error,
                    operation="_process_response_implementation",
                    severity=ErrorSeverity.WARNING,
                    details=details
                )
                
                # Add a user-friendly message to the state
                state.add_message("assistant", "I couldn't process your request. Please try again.")
                
                # Return the state with the error message
                return state
                
        except Exception as e:
            # Handle any exceptions during processing
            logger.error(f"Error processing {self.agent_name} response: {str(e)}")
            
            # Create error details
            details = {
                "response_type": type(response).__name__ if 'response' in locals() else None,
                "state_messages_count": len(state.messages) if hasattr(state, 'messages') else 0,
                "state_plan_count": len(state.plan) if hasattr(state, 'plan') else 0
            }
            
            # Add a user-friendly message to the state
            state.add_message("assistant", "An error occurred while processing your request. Please try again.")
            
            # Return a NoValidResponse with error information
            return self._handle_agent_error(
                error=e,
                operation="_process_response_implementation",
                severity=ErrorSeverity.ERROR,
                details=details
            )