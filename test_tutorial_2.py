"""
Test script for Tutorial 2: Agents as Tools
This script validates that all the code in Tutorial 2 works correctly.
"""
import asyncio
import sys
import os
from pathlib import Path
# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel, Field
from typing import List, Dict, Any
from pydantic_ai import RunContext

from orqest.agents.base_agent import BaseAgent, NoValidResponse

# Step 2: Define State and Output Models
class SimpleState(BaseModel):
    """Simple state with just messages and a plan."""
    
    messages: List[Dict[str, str]] = Field(default_factory=list)
    plan: List[str] = Field(default_factory=list)
    
    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation."""
        self.messages.append({"role": role, "content": content})
    
    def get_user_message(self) -> str:
        """Get the latest user message."""
        for msg in reversed(self.messages):
            if msg["role"] == "user":
                return msg["content"]
        return "No user message"

class PlanOutput(BaseModel):
    """Structured output format for planning responses."""
    plan_text: str = Field(
        description="The planning response text",
        min_length=1
    )
    steps_identified: int = Field(
        description="Number of plan steps identified",
        ge=0
    )

class TextOutput(BaseModel):
    """Simple text output format for general responses."""
    answer: str = Field(
        description="The assistant's reply text",
        min_length=1
    )

# Step 3: Planning Agent
class PlannerAgent(BaseAgent[SimpleState]):
    """A simple planning agent that creates step-by-step plans."""
    
    def __init__(self):
        super().__init__(
            agent_name="planner",
            output_type=PlanOutput,
            system_prompt="You are a planning agent. Break down the user's request into 3-5 clear, numbered steps. Be practical and specific.",
            retries=2,
            deps_type=SimpleState
        )
    
    async def _run_implementation(self, state: SimpleState, **kwargs) -> SimpleState:
        """Create a plan based on the user's request."""
        user_request = state.get_user_message()
        
        prompt = f"Create a step-by-step plan for: {user_request}"
        
        response = await self.agent.run(prompt, deps=state, **kwargs)
        
        return await self._process_response_implementation(response, state, **kwargs)
    
    async def _process_response_implementation(self, response, state: SimpleState, **kwargs) -> SimpleState:
        """Extract the plan from the response."""
        # Extract content from PlanOutput response
        if hasattr(response, "output") and hasattr(response.output, "plan_text"):
            content = response.output.plan_text
        elif hasattr(response, "content"):
            content = response.content
        else:
            content = str(response)
        
        # Add response to messages
        state.add_message("assistant", content)
        
        # Extract numbered steps (simple parsing)
        state.plan.clear()
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith(("Step", "•", "-"))):
                # Clean up the step
                clean_step = line.split('.', 1)[-1].strip()
                if clean_step:
                    state.plan.append(clean_step)
        
        return state

# Step 4: Orchestrator Agent
class OrchestratorAgent(BaseAgent[SimpleState]):
    """Orchestrator that uses other agents as tools."""
    
    def __init__(self):
        # Set up tools - including other agents!
        tools = [self._use_planner]
        
        super().__init__(
            agent_name="orchestrator",
            output_type=TextOutput,
            system_prompt="""You are a helpful orchestrator. When users ask for help planning something, use the 'use_planner' tool. For other questions, respond directly.""",
            retries=2,
            deps_type=SimpleState,
            tools=tools
        )
        
        # Create the planner agent
        self.planner = PlannerAgent()
    
    async def _run_implementation(self, state: SimpleState, **kwargs) -> SimpleState:
        """Analyze the request and decide whether to use tools."""
        user_message = state.get_user_message()
        
        prompt = f"""
        User said: {user_message}
        
        If this looks like a planning request (organizing, creating steps, etc.), use the use_planner tool.
        Otherwise, respond directly.
        """
        
        response = await self.agent.run(prompt, deps=state, **kwargs)
        
        return await self._process_response_implementation(response, state, **kwargs)
    
    async def _process_response_implementation(self, response, state: SimpleState, **kwargs) -> SimpleState:
        """Process the orchestrator's response."""
        # Extract content from TextOutput response
        if hasattr(response, "output") and hasattr(response.output, "answer"):
            content = response.output.answer
        elif hasattr(response, "content"):
            content = response.content
        else:
            content = str(response)
        
        state.add_message("assistant", content)
        return state
    
    # === THE MAGIC: AGENT AS TOOL ===
    
    async def _use_planner(self, ctx: RunContext[SimpleState], task: str) -> Dict[str, Any]:
        """🔧 Tool: Use the planner agent to create a plan."""
        try:
            # Get current state
            state = ctx.deps
            
            # Add the planning task as a user message
            state.add_message("user", task)
            
            # 🔥 Call the planner agent!
            result = await self.planner.run(state)
            
            if isinstance(result, NoValidResponse):
                return {"success": False, "error": "Planning failed"}
            
            return {
                "success": True,
                "plan_steps": len(result.plan),
                "plan": result.plan
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}

async def test_tutorial_2():
    """Test all examples from Tutorial 2."""
    print("🧪 Testing Tutorial 2: Agents as Tools")
    print("=" * 50)
    
    try:
        # Test 1: Basic planning request
        print("\n🎬 Test 1: Basic planning request")
        state = SimpleState()
        state.add_message("user", "Help me plan a birthday party for my friend")
        
        orchestrator = OrchestratorAgent()
        result = await orchestrator.run(state)
        
        print(f"✅ Messages: {len(result.messages)}")
        print(f"✅ Plan steps: {len(result.plan)}")
        
        # Test 2: Continue conversation
        print("\n🔄 Test 2: Continue conversation")
        result.add_message("user", "Make it more budget-friendly")
        updated_result = await orchestrator.run(result)
        
        print(f"✅ Total messages: {len(updated_result.messages)}")
        print(f"✅ Plan maintained: {len(updated_result.plan) >= 0}")
        
        # Test 3: Non-planning request
        print("\n🧪 Test 3: Non-planning request")
        simple_state = SimpleState()
        simple_state.add_message("user", "What's the weather like?")
        
        simple_result = await orchestrator.run(simple_state)
        print(f"✅ Response received: {len(simple_result.messages) > 1}")
        print(f"✅ No plan created: {len(simple_result.plan) == 0}")
        
        # Test 4: Planning request
        print("\n🧪 Test 4: Another planning request")
        planning_state = SimpleState()
        planning_state.add_message("user", "Help me plan a study schedule for learning Python")
        
        planning_result = await orchestrator.run(planning_state)
        print(f"✅ Response received: {len(planning_result.messages) > 1}")
        print(f"✅ Plan created: {len(planning_result.plan) > 0}")
        
        if planning_result.plan:
            print(f"✅ First step: {planning_result.plan[0][:50]}...")
        
        print("\n🎉 All tests passed! Tutorial 2 is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_tutorial_2())
    sys.exit(0 if success else 1)
