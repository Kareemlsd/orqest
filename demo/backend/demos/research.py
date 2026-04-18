"""Research Assistant demo — mock web search + inline citations."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response
from pydantic_ai import Agent, Tool
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from demo.backend._config import MODEL
from demo.backend.tools import web_search

router = APIRouter(prefix="/api/demos/research")


SYSTEM_PROMPT = """\
You are a research assistant. When the user asks a factual question:

1. Call the `web_search` tool with a focused query.
2. Read the returned JSON sources (each has an `index`, `title`, `url`, `snippet`).
3. Synthesize a clear answer. Cite sources inline using numbered markers like [1], [2], [3].
4. End your response with a **Sources** section listing all cited sources in order:

   **Sources**
   [1] Title — URL
   [2] Title — URL

Citations must match the source indices. If a source wasn't used, don't cite it.

Answer concisely — 2-4 short paragraphs. Let the citations do the heavy lifting.
"""


agent = Agent(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    tools=[
        Tool(
            web_search,
            name="web_search",
            description="Search the web for current information. Returns JSON list of sources.",
        ),
    ],
)


@router.post("/chat")
async def chat(request: Request) -> Response:
    """Stream agent responses; frontend parses citations into Sources sidebar."""
    return await VercelAIAdapter.dispatch_request(request, agent=agent)
