"""Pluggable web search + fetch tools for Orqest agents.

Autonomous agents that decide to *investigate* a question on the open
web need two reliable primitives: a ranked search, and a content-aware
page fetch. ``web_search`` and ``web_fetch`` provide both as async
functions that agents call directly — no provider-specific SDKs in the
calling code, no hard dependency on any single search vendor.

Provider selection is driven by env vars so ops can swap backends
without touching agent code:

* ``ORQEST_WEB_PROVIDER`` — one of ``"tavily"`` (default),
  ``"exa"``, ``"brave"``, ``"serper"``, or ``"none"`` (disabled).
* ``ORQEST_WEB_API_KEY`` — the API key for the selected provider.

When ``ORQEST_WEB_API_KEY`` is unset or the provider is ``"none"`` the
tools degrade gracefully: ``web_search`` returns an empty result list
with a ``disabled_reason`` note, ``web_fetch`` still works for public
URLs (no key required for a plain GET). This lets investigation tools
stay functional in offline / CI settings without tripping on missing
credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_RESULTS = 5
MAX_FETCH_CHARS = 8_000

_PROVIDER_ENV = "ORQEST_WEB_PROVIDER"
_API_KEY_ENV = "ORQEST_WEB_API_KEY"


@dataclass
class WebSearchResult:
    """One hit returned by :func:`web_search`."""

    title: str
    url: str
    snippet: str
    score: float | None = None


@dataclass
class WebSearchResponse:
    """Full response envelope returned by :func:`web_search`."""

    query: str
    results: list[WebSearchResult] = field(default_factory=list)
    provider: str = "none"
    disabled_reason: str | None = None


@dataclass
class WebFetchResult:
    """Content fetched by :func:`web_fetch`."""

    url: str
    status_code: int
    content_type: str
    text: str
    truncated: bool


async def web_search(
    query: str,
    *,
    k: int = DEFAULT_RESULTS,
    provider: str | None = None,
    api_key: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> WebSearchResponse:
    """Search the web and return up to *k* ranked hits.

    Selects the provider from the ``provider`` argument, then from
    ``ORQEST_WEB_PROVIDER``, then defaults to ``"tavily"``. Degrades
    gracefully when no API key is available — returns an empty
    :class:`WebSearchResponse` with ``disabled_reason`` explaining why.

    Args:
        query: Free-text search query.
        k: Maximum number of results.
        provider: Override of the env-selected provider.
        api_key: Override of the env-supplied API key.
        timeout_s: HTTP timeout in seconds.
    """
    resolved_provider = (provider or os.getenv(_PROVIDER_ENV, "tavily")).lower()
    resolved_key = api_key or os.getenv(_API_KEY_ENV)

    if resolved_provider == "none":
        return WebSearchResponse(
            query=query, provider="none", disabled_reason="provider disabled",
        )
    if not resolved_key:
        return WebSearchResponse(
            query=query,
            provider=resolved_provider,
            disabled_reason=f"{_API_KEY_ENV} not set",
        )

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        if resolved_provider == "tavily":
            return await _search_tavily(client, query, k, resolved_key)
        if resolved_provider == "exa":
            return await _search_exa(client, query, k, resolved_key)
        if resolved_provider == "brave":
            return await _search_brave(client, query, k, resolved_key)
        if resolved_provider == "serper":
            return await _search_serper(client, query, k, resolved_key)

    return WebSearchResponse(
        query=query,
        provider=resolved_provider,
        disabled_reason=f"unknown provider '{resolved_provider}'",
    )


async def web_fetch(
    url: str,
    *,
    max_chars: int = MAX_FETCH_CHARS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> WebFetchResult:
    """Fetch *url* and return its (truncated) body as text.

    No API key needed — this is a plain GET. The body is truncated to
    ``max_chars`` to keep LLM context bounded; consumers that need the
    full body can pass ``max_chars=-1`` or zero to disable truncation.
    """
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "orqest-web-fetch/1.0"})

    text = response.text
    truncated = bool(max_chars > 0 and len(text) > max_chars)
    if truncated:
        text = text[:max_chars]

    return WebFetchResult(
        url=str(response.url),
        status_code=response.status_code,
        content_type=response.headers.get("content-type", ""),
        text=text,
        truncated=truncated,
    )


# --- provider implementations ---------------------------------------------


async def _search_tavily(
    client: httpx.AsyncClient, query: str, k: int, api_key: str,
) -> WebSearchResponse:
    resp = await client.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": k,
            "include_answer": False,
        },
    )
    data = _safe_json(resp)
    results = [
        WebSearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", "") or "",
            score=item.get("score"),
        )
        for item in (data.get("results", []) if isinstance(data, dict) else [])
    ]
    return WebSearchResponse(query=query, provider="tavily", results=results)


async def _search_exa(
    client: httpx.AsyncClient, query: str, k: int, api_key: str,
) -> WebSearchResponse:
    resp = await client.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": api_key, "content-type": "application/json"},
        json={"query": query, "numResults": k, "useAutoprompt": False},
    )
    data = _safe_json(resp)
    raw = data.get("results", []) if isinstance(data, dict) else []
    results = [
        WebSearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("text", "") or item.get("snippet", ""),
            score=item.get("score"),
        )
        for item in raw
    ]
    return WebSearchResponse(query=query, provider="exa", results=results)


async def _search_brave(
    client: httpx.AsyncClient, query: str, k: int, api_key: str,
) -> WebSearchResponse:
    resp = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": k},
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
    )
    data = _safe_json(resp)
    web_block = data.get("web", {}) if isinstance(data, dict) else {}
    results = [
        WebSearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("description", ""),
        )
        for item in web_block.get("results", [])
    ]
    return WebSearchResponse(query=query, provider="brave", results=results)


async def _search_serper(
    client: httpx.AsyncClient, query: str, k: int, api_key: str,
) -> WebSearchResponse:
    resp = await client.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "content-type": "application/json"},
        json={"q": query, "num": k},
    )
    data = _safe_json(resp)
    organic = data.get("organic", []) if isinstance(data, dict) else []
    results = [
        WebSearchResult(
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
        )
        for item in organic
    ]
    return WebSearchResponse(query=query, provider="serper", results=results)


def _safe_json(response: httpx.Response) -> Any:
    """Return parsed JSON or an empty dict if the response isn't JSON."""
    try:
        return response.json()
    except ValueError:
        return {}
