"""Web research tools — thin wrappers over :mod:`orqest.tools.web`.

The Orqest tools handle provider routing, API-key lookup, and graceful
degradation. These wrappers just:

1. Emit ``tool.web_search.*`` / ``tool.web_fetch.*`` events on the session
   bus so the frontend can light up the ToolCard + ComputerPane.
2. Serialise the pydantic response back into a compact string the agent
   can fit in its context without hallucinating fields.

Reference: ``docs/concepts/web-tools.md`` in the Orqest repo.
"""

from __future__ import annotations

import json
from typing import Annotated

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from orqest.tools import web_fetch as _orqest_web_fetch
from orqest.tools import web_search as _orqest_web_search

from polymath.config import get_default_config
from polymath.runtime import emit
from polymath.state import PolymathState


async def _web_search(
    ctx: RunContext[PolymathState],
    query: Annotated[str, "The query, phrased as a user would type it."],
    k: Annotated[int, "Number of results (default 5)."] = 5,
) -> str:
    """Search the web via the configured provider. Returns JSON with results + citations."""
    cfg = get_default_config()
    sid = ctx.deps.session_id
    await emit(sid, "tool.web_search.started", {"query": query, "k": k})
    response = await _orqest_web_search(
        query,
        k=k,
        provider=cfg.WEB_PROVIDER,
        api_key=cfg.WEB_API_KEY,
    )
    payload = {
        "provider": response.provider,
        "disabled_reason": response.disabled_reason,
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "score": r.score}
            for r in response.results
        ],
    }
    await emit(
        sid,
        "tool.web_search.completed",
        {"hits": len(response.results), "provider": response.provider},
    )
    return json.dumps(payload, ensure_ascii=False)


async def _web_fetch(
    ctx: RunContext[PolymathState],
    url: Annotated[str, "Fully-qualified URL to GET."],
    max_chars: Annotated[int, "Truncate response body at this many characters."] = 8000,
) -> str:
    """Fetch a URL. Returns JSON with status, content_type, truncated body."""
    sid = ctx.deps.session_id
    await emit(sid, "tool.web_fetch.started", {"url": url})
    result = await _orqest_web_fetch(url, max_chars=max_chars)
    await emit(
        sid,
        "tool.web_fetch.completed",
        {
            "url": url,
            "status_code": result.status_code,
            "truncated": result.truncated,
            "bytes": len(result.text),
        },
    )
    return json.dumps(
        {
            "url": result.url,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "text": result.text,
            "truncated": result.truncated,
        },
        ensure_ascii=False,
    )


web_search = Tool(_web_search, name="web_search")
web_fetch = Tool(_web_fetch, name="web_fetch")
