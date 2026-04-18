"""Task Planner demo — Manus-style task decomposition with live progress.

Uses pydantic-ai's structured output via `output_type` to force the model
to emit exactly the schema we need. The VercelAIAdapter streams the
partial JSON as the model generates each field, so the frontend can
render the task tree as it builds up, token by token.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from demo.backend._config import MODEL

router = APIRouter(prefix="/api/demos/tasks")


class TaskStep(BaseModel):
    """A single step in the task plan."""

    index: int = Field(description="1-based step number")
    description: str = Field(description="Concise action for this step")
    status: Literal["running", "complete"] = Field(
        description="Current state — 'running' while executing, 'complete' once done"
    )
    result: str = Field(description="One short sentence describing what was accomplished")


class TaskPlan(BaseModel):
    """A decomposed plan with executed steps."""

    goal: str = Field(description="The high-level goal from the user")
    steps: list[TaskStep] = Field(
        description=(
            "4-6 sequential steps. Each step MUST have status='complete' and a "
            "concrete result describing what was done. Simulate the work — you "
            "don't have real tools, so describe plausible outcomes."
        )
    )
    summary: str = Field(
        description="2-3 sentence summary of the overall plan and outcome"
    )


SYSTEM_PROMPT = """\
You are an autonomous task planner. For any goal the user gives you, \
decompose it into 4-6 concrete steps, then "execute" each step by \
describing what would happen. Always return a complete TaskPlan with \
every step status='complete' and a specific result for each step. \
Simulate plausible outcomes — you don't have real tools."""


agent = Agent(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    output_type=TaskPlan,
)


@router.post("/chat")
async def chat(request: Request) -> Response:
    """Stream a structured TaskPlan. Frontend renders it as it builds."""
    return await VercelAIAdapter.dispatch_request(request, agent=agent)
