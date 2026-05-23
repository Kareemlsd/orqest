"""Multimodal Analyst demo — image upload + vision analysis."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response
from pydantic_ai import Agent
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from demo.backend._config import MODEL

router = APIRouter(prefix="/api/demos/multimodal")


SYSTEM_PROMPT = """\
You are a multimodal analyst. The user may send you images along with text. \
When you receive an image:

1. Describe what you see — subjects, composition, notable details.
2. Extract any text visible in the image.
3. If relevant, suggest 2-3 follow-up questions the user might ask.

Be concrete and observational. Avoid speculation beyond what's in the image. \
When the user sends only text (no image), answer normally.
"""


agent = Agent(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
)


@router.post("/chat")
async def chat(request: Request) -> Response:
    """Stream agent responses. VercelAIAdapter handles image attachments natively."""
    return await VercelAIAdapter.dispatch_request(request, agent=agent)
