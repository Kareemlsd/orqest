"""Planner agent created using the base agent from Orqest"""
import logging
from typing import Any, List, Optional, Dict
import asyncio

from pydantic import BaseModel, Field

from orqest.agents.base_agent import BaseAgent

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

class NoValidResponse(BaseModel):
    """No valid response from the planner agent"""
    messages: str = Field(
        description="No valid response from the planner agent",
        default_factory=list
    )

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

        return state


orchestrator = OrchestratorAgent()

state = GlobalState()
state.add_message("user", "What are the steps to to take to bake a cake?")

async def run_orchestrator():
    """Run the orchestrator agent"""
    return await orchestrator.run(state)

result_state = run_orchestrator()

print(result_state.plan)
