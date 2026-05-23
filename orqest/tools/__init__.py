"""First-party tools for Orqest agents (web, future: fs, shell)."""

from orqest.tools.web import (
    WebFetchResult,
    WebSearchResponse,
    WebSearchResult,
    web_fetch,
    web_search,
)

__all__ = [
    "WebFetchResult",
    "WebSearchResponse",
    "WebSearchResult",
    "web_fetch",
    "web_search",
]
