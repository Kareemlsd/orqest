"""Planner agent created using the base agent from Orqest"""
import logging
from typing import Any, List, Optional, Dict
import asyncio

from pydantic import BaseModel, Field

from orqest.agents.base_agent import BaseAgent, NoValidResponse

logger = logging.getLogger(__name__)

class GlobalState(BaseModel):
    """Global state for the planner agent"""
    messages: List[Dict[str, Any]] = Field(default_factory=list)

    # Current plan
    plan: List[str] = Field(default_factory=list)

    # chat history
    chat_history: List[str] = Field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the global state"""
        self.messages.append({"role": role, "content": content})

    def get_latest_user_message(self) -> Optional[str]:
        """Get the latest user message from the global state"""
        for message in reversed(self.messages):
            if message["role"] == "user":
                return message["content"]
        return None

    def get_latest_assistant_message(self) -> Optional[str]:
        """Get the latest assistant message from the global state"""
        for message in reversed(self.messages):
            if message["role"] == "assistant":
                return message["content"]
        return None


class PlannerAgent(BaseAgent[GlobalState]):
    """Planner agent created using the base agent from Orqest"""

    def __init__(self):
        """Initialize the planner agent"""
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
        """Run the planner agent."""
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

        response = await self.agent.run(prompt, message_history=state.chat_history, **kwargs)
        state.chat_history.extend(response.all_messages())

        return await self._process_agent_response(response, state)
        
    async def _process_agent_response(self, response, state: GlobalState, **kwargs) -> GlobalState:
        """Process the agent response and update the state.
        
        Args:
            response: The response from the agent.
            state: The current state of the agent.
            
        Returns:
            Updated state after processing the response.
        """
        # Check if the response is valid
        if hasattr(response, "output") and response.output:
            # Extract plan from the response if available
            if hasattr(response.output, "plan") and response.output.plan:
                state.plan = response.output.plan
            
            # Add the assistant's response to the messages
            content = response.content if hasattr(response, "content") else str(response.output)
            state.add_message("assistant", content)
            
            return state
        else:
            # Handle invalid response
            state.add_message("assistant", "I couldn't generate a valid plan. Please try again.")
            return state

    def _analyze_task_complexity(self, task_description: str) -> dict[str, str]:
        # Simple complexity analysis, return always the same
        return {
            "complexity": "simple"
        }


class OrchestratorAgent(BaseAgent[GlobalState]):
    """Orchestrator agent created using the base agent from Orqest"""

    def __init__(self):
        """Initialize the orchestrator agent"""
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
        return """
            You are a orchestrator agent. Your goal is to orchestrate the planning and execution of tasks.
            Your role is to:
            1. Orchestrate the planning and execution of tasks.
            2. Provide a detailed plan for the task.
            Use the tools strategically based on the current workflow state and user needs.
            """

    async def run(self, state: GlobalState, **kwargs) -> GlobalState:
        """Run the coordinator agent to manage the workflow."""

        # Analyze current state and determine next steps
        prompt = f"""
        Current workflow state: {state.plan}
        Current messages: {state.get_latest_user_message()}
        
        Please analyze the current workflow state and determine the next steps.
        Consider what information is missing and what tools are available.
        """

        response = await self.agent.run(prompt, message_history=state.chat_history, **kwargs)
        state.chat_history.extend(response.all_messages())

        return await self._process_agent_response(response, state)
        
    async def _call_planner_agent(self, query: str) -> dict[str, list[str]]:
        """Call the planner agent to create a plan for the given query.
        
        Args:
            query: The query to plan for.
            
        Returns:
            A dictionary containing the plan.
        """
        # Create a temporary state for the planner agent
        temp_state = GlobalState()
        temp_state.add_message("user", query)
        
        # Run the planner agent
        result_state = await self.planner_agent.run(temp_state)
        
        # Return the plan
        return {
            "plan": result_state.plan
        }
        
    async def _process_agent_response(self, response, state: GlobalState, **kwargs) -> GlobalState:
        """Process the agent response and update the state.
        
        Args:
            response: The response from the agent.
            state: The current state of the agent.
            
        Returns:
            Updated state after processing the response.
        """
        # Check if the response is valid
        if hasattr(response, "output") and response.output:
            # Extract plan from the response if available
            if hasattr(response.output, "plan") and response.output.plan:
                state.plan = response.output.plan
            
            # Add the assistant's response to the messages
            content = response.content if hasattr(response, "content") else str(response.output)
            state.add_message("assistant", content)
            
            return state
        else:
            # Handle invalid response
            state.add_message("assistant", "I couldn't process your request. Please try again.")
            return state


orchestrator = OrchestratorAgent()

state = GlobalState()
state.add_message("user", "What are the steps to to take to bake a cake?")

async def run_orchestrator():
    """Run the orchestrator agent"""
    return await orchestrator.run(state)

async def main():
    """Main function to run the orchestrator agent"""
    result_state = await run_orchestrator()
    print(result_state.plan)

# Run the main function if this script is executed directly
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
