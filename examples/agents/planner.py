"""Example planner agent implementation.

This module contains an example implementation of a planner agent using the Orqest framework.
It demonstrates how to extend the BaseAgent class to create a specialized agent.
"""
import logging
from typing import Any, Dict, Optional

from orqest.agents.base_agent import BaseAgent, NoValidResponse
from orqest.errors import ErrorSeverity

from examples.agents.state import GlobalState

logger = logging.getLogger(__name__)

class PlannerAgent(BaseAgent[GlobalState]):
    """Example planner agent created using the base agent from Orqest.
    
    This agent is responsible for decomposing user questions into subquestions
    and creating detailed plans for tasks.
    """

    def __init__(self):
        """Initialize the planner agent."""
        super().__init__(
            agent_name="planner_agent",
            output_type=GlobalState | NoValidResponse,
            system_prompt="You are a planning agent. Your goal is to decompose the user's question into subquestions.",
            retries=2,
            tools=[
                self._analyze_task_complexity,
            ]
        )

    async def run(self, state: GlobalState, **kwargs) -> GlobalState:
        """Run the planner agent.
        
        Args:
            state: The current state of the conversation.
            **kwargs: Additional keyword arguments to pass to the agent.
            
        Returns:
            Updated state after the agent has processed it.
        """
        try:
            # Ensure a starting user message is present
            if not state.get_latest_user_message():
                state.messages.append({"role": "user", "content": "What is your question?"})

            user_message = state.get_latest_user_message()

            # Enhanced prompt that encourages tool use
            prompt = (
                f"You are a planning agent. Your goal is to decompose the user's question into subquestions. "
                f"Please create a detailed plan for this task. User message: {user_message}"
                f"1. Analyze the complexity of the task."
                f" Then provide a comprehensive plan with clear steps."
            )

            # Log the operation
            logger.info(f"Running planner agent with prompt: {prompt[:100]}...")

            # Execute the agent
            response = await self.agent.run(prompt, message_history=state.chat_history, **kwargs)
            state.chat_history.extend(response.all_messages())

            # Process the response
            return await self._process_agent_response(response, state)
            
        except Exception as e:
            # Handle the error using the standardized error handling
            logger.error(f"Error running planner agent: {str(e)}")
            
            # Create error details
            details = {
                "user_message": user_message if 'user_message' in locals() else None,
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
                logger.info(f"Successfully processed response for planner agent")
                
                return state
            else:
                # Handle invalid response with standardized error handling
                logger.warning("Received invalid response from planner agent")
                
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
                state.add_message("assistant", "I couldn't generate a valid plan. Please try again.")
                
                # Return the state with the error message
                return state
                
        except Exception as e:
            # Handle any exceptions during processing
            logger.error(f"Error processing agent response: {str(e)}")
            
            # Create error details
            details = {
                "response_type": type(response).__name__ if 'response' in locals() else None,
                "state_messages_count": len(state.messages) if hasattr(state, 'messages') else 0,
                "state_plan_count": len(state.plan) if hasattr(state, 'plan') else 0
            }
            
            # Add a user-friendly message to the state
            state.add_message("assistant", "An error occurred while processing the response. Please try again.")
            
            # Return a NoValidResponse with error information
            return self._handle_agent_error(
                error=e,
                operation="_process_agent_response",
                severity=ErrorSeverity.ERROR,
                details=details
            )

    def _analyze_task_complexity(self, task_description: str) -> Dict[str, str]:
        """Analyze the complexity of a task.
        
        Args:
            task_description: The description of the task to analyze.
            
        Returns:
            A dictionary containing the complexity assessment.
        """
        # Simple complexity analysis, return always the same
        return {
            "complexity": "simple"
        }