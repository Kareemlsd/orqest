"""Orqest demo backend — FastAPI + VercelAIAdapter streaming.

A research assistant agent built with Orqest that demonstrates:
- Streaming text responses to the Vercel AI SDK frontend
- Tool calls visible in the UI (web search, analysis)
- Structured output via pydantic-ai

Run: cd demo/backend && uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import json
from datetime import datetime
from http import HTTPStatus

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError
from pydantic_ai import Agent, Tool

from orqest import load_config
from orqest.agents import BaseAgent, GlobalState

# Load orqest config from .env
config = load_config()

# --- Define tools the agent can use ---


async def get_current_time() -> str:
    """Get the current date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def analyze_topic(topic: str) -> str:
    """Analyze a topic and return key facts. Use this when the user asks about a specific subject."""
    # In a real app, this would call a knowledge base or search API
    return (
        f"Analysis of '{topic}':\n"
        f"- This is a complex topic with multiple dimensions\n"
        f"- Key areas to consider: fundamentals, applications, recent developments\n"
        f"- Recommended: break this into subtopics for deeper analysis"
    )


async def calculate(expression: str) -> str:
    """Evaluate a mathematical expression. Use for any math calculations."""
    try:
        # Safe eval for basic math
        allowed = set("0123456789+-*/().% ")
        if all(c in allowed for c in expression):
            result = eval(expression)  # noqa: S307
            return f"{expression} = {result}"
        return "Invalid expression — only basic arithmetic is supported"
    except Exception as e:
        return f"Calculation error: {e}"


# --- Create the pydantic-ai Agent with tools ---

import os
os.environ.setdefault("OPENAI_API_KEY", config.llm_api_key)

agent = Agent(
    model=config.llm_model,
    system_prompt=(
        "You are a helpful research assistant powered by the Orqest framework. "
        "You have access to tools for getting the current time, analyzing topics, "
        "and performing calculations. Use them when appropriate.\n\n"
        "When using tools, explain what you're doing so the user can see "
        "the agent's reasoning process in real-time.\n\n"
        "Be concise, direct, and helpful. No filler words."
    ),
    tools=[
        Tool(get_current_time, name="get_time", description="Get the current date and time"),
        Tool(analyze_topic, name="analyze", description="Analyze a topic and return key facts"),
        Tool(calculate, name="calculate", description="Evaluate a math expression"),
    ],
)

# --- FastAPI app ---

app = FastAPI(title="Orqest Demo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/chat")
async def chat(request: Request) -> Response:
    """Stream agent responses using the Vercel AI Data Stream Protocol."""
    from pydantic_ai.ui import SSE_CONTENT_TYPE
    from pydantic_ai.ui.vercel_ai import VercelAIAdapter

    accept = request.headers.get("accept", SSE_CONTENT_TYPE)
    try:
        run_input = VercelAIAdapter.build_run_input(await request.body())
    except ValidationError as e:
        return Response(
            content=json.dumps(e.json()),
            media_type="application/json",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    adapter = VercelAIAdapter(
        agent=agent, run_input=run_input, accept=accept
    )
    event_stream = adapter.run_stream()
    sse_event_stream = adapter.encode_stream(event_stream)
    return StreamingResponse(sse_event_stream, media_type=accept)


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "framework": "orqest",
        "model": config.llm_model,
    }
