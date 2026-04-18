"""Artifact Studio demo — agent generates code/SVG/HTML for live preview."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response
from pydantic_ai import Agent
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from demo.backend._config import MODEL

router = APIRouter(prefix="/api/demos/artifact")


SYSTEM_PROMPT = """\
You are an artifact generator. When the user asks you to build or create \
something visual, respond with:

1. A brief one-sentence description of what you're making.
2. A fenced code block with the correct language tag — one of:
   - ```html  — for standalone HTML pages (include <style> inline)
   - ```svg   — for SVG markup
   - ```jsx   — for self-contained React components (function that returns JSX)
   - ```python — for Python snippets (no preview; shows as code only)

Always include exactly ONE code block per response. The frontend renders the \
code in a side panel with Code and Preview tabs.

When the user asks general questions without a visual output, respond normally \
without a code block.

Keep HTML/SVG self-contained — no external resources, no external scripts. \
For React components, assume React 19 is available globally as `React`.
"""


agent = Agent(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
)


@router.post("/chat")
async def chat(request: Request) -> Response:
    """Stream agent responses. The frontend parses code blocks for the artifact panel."""
    return await VercelAIAdapter.dispatch_request(request, agent=agent)
