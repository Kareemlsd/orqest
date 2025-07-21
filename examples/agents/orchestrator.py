"""Example orchestrator agent implementation.

This module contains an example implementation of an orchestrator agent using the Orqest framework.
It demonstrates how to extend the BaseAgent class to create a specialized agent that can use other agents as tools.
"""
import logging
from typing import Any, Dict, List, Optional

from pydantic_ai import RunContext

from orqest.agents.base_agent import BaseAgent, NoValidResponse
from orqest.errors import ErrorSeverity, ErrorContext, ToolError

from examples.agents.state import GlobalState
from examples.agents.planner import PlannerAgent

logger = logging.getLogger(__name__)

class OrchestratorAgent(BaseAgent[GlobalState]):
    """Example orchestrator agent created using the base agent from Orqest.
    
    This agent is responsible for orchestrating the planning and execution of tasks.
    It can call other agents, such as the PlannerAgent, to help with specific tasks.
    This demonstrates how to compose agents hierarchically using the "Agent as Tools" pattern.
    """

    def __init__(self):
        """Initialize the orchestrator agent."""
        super().__init__(
            agent_name="orchestrator",
            output_type=GlobalState | NoValidResponse,
            system_prompt=self._build_system_prompt(),
            retries=2,
            tools=[
                self._call_planner_agent,
            ]
        )

        # Initialize sub-agent planner:
        self.planner_agent = PlannerAgent()

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the orchestrator agent.
        
        Returns:
            The system prompt string.
        """
        return """
            You are a orchestrator agent. Your goal is to orchestrate the planning and execution of tasks.
            Your role is to:
            1. Orchestrate the planning and execution of tasks.
            2. Provide a detailed plan for the task.
            Use the tools strategically based on the current workflow state and user needs.
            """

    async def run(self, state: GlobalState, **kwargs) -> GlobalState:
        """Run the coordinator agent to manage the workflow.
        
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
            logger.info(f"Running orchestrator agent with prompt: {prompt[:100]}...")

            # Execute the agent
            response = await self.agent.run(prompt, deps=state, message_history=state.chat_history, **kwargs)
            state.chat_history.extend(response.all_messages())

            # Process the response
            return await self._process_agent_response(response, state)
            
        except Exception as e:
            # Handle the error using the standardized error handling
            logger.error(f"Error running orchestrator agent: {str(e)}")
            
            # Create error details
            details = {
                "user_message": state.get_latest_user_message() if hasattr(state, 'get_latest_user_message') else None,
                "state_messages_count": len(state.messages) if hasattr(state, 'messages') else 0,
                "state_plan_count": len(state.plan) if hasattr(state, 'plan') else 0
            }
            
            # Return a NoValidResponse with error information
            return self._handle_agent_error(
                error=e,
                operation="run",
                severity=ErrorSeverity.ERROR,
                details=details
            )
        
    async def _call_planner_agent(self, ctx: RunContext[GlobalState], query: str) -> Dict[str, List[str]]:
        """Call the planner agent to create a plan for the given query.
        
        This method demonstrates how to use one agent as a tool for another agent,
        implementing the "Agent as Tools" pattern.
        
        Args:
            ctx: The run context containing the global state.
            query: The query to plan for.
            
        Returns:
            A dictionary containing the plan.
        """
        try:
            # Log the operation
            logger.info(f"Calling planner agent with query: {query[:100]}...")
            
            # Get the state from the context
            state = ctx.deps
            
            # Add the query to the state
            state.add_message("user", query)
            
            # Run the planner agent
            result_state = await self.planner_agent.run(state)
            
            # Check if the result is a NoValidResponse
            if isinstance(result_state, NoValidResponse):
                # Log the error
                logger.warning(f"Planner agent returned NoValidResponse: {result_state.error_message}")
                
                # Create error details
                details = {
                    "query": query[:100] + "..." if len(query) > 100 else query,
                    "error_type": result_state.error_type,
                    "error_message": result_state.error_message
                }
                
                # Create a tool error
                error = ValueError(f"Planner agent failed: {result_state.error_message}")
                
                # Raise a ToolError to be caught by the orchestrator's run method
                raise ToolError(
                    message=f"Planner agent failed to generate a plan",
                    severity=ErrorSeverity.WARNING,
                    context=self._create_error_context(
                        operation="_call_planner_agent",
                        details=details
                    ),
                    exception=error
                )
            
            # Log successful execution
            logger.info(f"Planner agent successfully generated a plan with {len(result_state.plan)} steps")
            
            # Return the plan
            return {
                "plan": result_state.plan
            }
            
        except ToolError:
            # Re-raise ToolError to be caught by the orchestrator's run method
            raise
            
        except Exception as e:
            # Handle any other exceptions
            logger.error(f"Error calling planner agent: {str(e)}")
            
            # Create error details
            details = {
                "query": query[:100] + "..." if len(query) > 100 else query,
                "error_type": type(e).__name__,
                "error_message": str(e)
            }
            
            # Create and raise a ToolError
            raise ToolError(
                message=f"Error calling planner agent: {str(e)}",
                severity=ErrorSeverity.ERROR,
                context=self._create_error_context(
                    operation="_call_planner_agent",
                    details=details
                ),
                exception=e
            )
        
    async def _process_agent_response(self, response, state: GlobalState, **kwargs) -> GlobalState:
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
                logger.info(f"Successfully processed response for orchestrator agent")
                
                return state
            else:
                # Handle invalid response with standardized error handling
                logger.warning("Received invalid response from orchestrator agent")
                
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
                    operation="_process_agent_response",
                    severity=ErrorSeverity.WARNING,
                    details=details
                )
                
                # Add a user-friendly message to the state
                state.add_message("assistant", "I couldn't process your request. Please try again.")
                
                # Return the state with the error message
                return state
                
        except Exception as e:
            # Handle any exceptions during processing
            logger.error(f"Error processing orchestrator agent response: {str(e)}")
            
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
                operation="_process_agent_response",
                severity=ErrorSeverity.ERROR,
                details=details
            )