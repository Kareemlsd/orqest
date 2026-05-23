"""Chat demo — streaming chat with basic tools."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response
from pydantic_ai import Agent, Tool
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from demo.backend._config import MODEL
from demo.backend.tools import analyze_topic, calculate, get_current_time

router = APIRouter(prefix="/api/demos/chat")

agent = Agent(
    model=MODEL,
    system_prompt=(
        "You are a helpful research assistant powered by Orqest. "
        "You have tools for time, topic analysis, and calculations. "
        "Use them when appropriate. Be concise and direct."
    ),
    tools=[
        Tool(get_current_time, name="get_time", description="Get current date and time"),
        Tool(analyze_topic, name="analyze", description="Analyze a topic and return key facts"),
        Tool(calculate, name="calculate", description="Evaluate a math expression"),
    ],
)


@router.post("/chat")
async def chat(request: Request) -> Response:
    """Stream agent responses via the Vercel AI Data Stream Protocol."""
    return await VercelAIAdapter.dispatch_request(request, agent=agent)
