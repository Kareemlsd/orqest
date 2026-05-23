"""ArXiv research tools — search + fetch paper metadata.

Two tools for the research-engine slice of Polymath:

* :func:`arxiv_search` — keyword search over the arxiv corpus with optional
  category + date filters. Returns ranked candidates with abstracts.
* :func:`arxiv_fetch` — fetch full metadata for a known arxiv id (post-search
  drill-down).

Both wrap the `arxiv` Python package (MIT). Network calls run in a thread via
``asyncio.to_thread`` because the underlying client is synchronous.

Reference: https://info.arxiv.org/help/api/
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Annotated, Literal

import arxiv  # type: ignore[import-not-found]
from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from polymath.runtime import emit
from polymath.state import PolymathState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SORT_MAP = {
    "relevance": arxiv.SortCriterion.Relevance,
    "lastUpdatedDate": arxiv.SortCriterion.LastUpdatedDate,
    "submittedDate": arxiv.SortCriterion.SubmittedDate,
}

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?$")


def _normalise_arxiv_id(raw: str) -> str:
    """Strip URL prefix / extract the numeric id from common surface forms.

    Accepts: ``2405.12345``, ``2405.12345v2``, ``arxiv:2405.12345``,
    ``https://arxiv.org/abs/2405.12345``, ``http://arxiv.org/pdf/2405.12345v1.pdf``.
    Returns the canonical ``YYMM.NNNNN[vN]`` form.
    """
    candidate = raw.strip()
    candidate = candidate.removeprefix("arxiv:").removeprefix("arXiv:")
    candidate = candidate.removesuffix(".pdf")
    for prefix in ("https://arxiv.org/abs/", "http://arxiv.org/abs/",
                   "https://arxiv.org/pdf/", "http://arxiv.org/pdf/",
                   "https://arxiv.org/html/", "http://arxiv.org/html/"):
        candidate = candidate.removeprefix(prefix)
    match = _ARXIV_ID_RE.search(candidate)
    return match.group(0) if match else candidate


def _serialise_result(r: arxiv.Result) -> dict:
    """Flatten an :class:`arxiv.Result` into a JSON-safe dict for the agent."""
    arxiv_id = r.entry_id.rsplit("/", 1)[-1]  # e.g. '2405.12345v2'
    return {
        "arxiv_id": arxiv_id,
        "title": r.title.strip(),
        "authors": [a.name for a in r.authors],
        "abstract": r.summary.strip(),
        "published": r.published.isoformat() if r.published else None,
        "updated": r.updated.isoformat() if r.updated else None,
        "categories": list(r.categories),
        "primary_category": r.primary_category,
        "pdf_url": r.pdf_url,
        "abs_url": r.entry_id,
        "html_url": f"https://arxiv.org/html/{_normalise_arxiv_id(arxiv_id)}",
        "comment": r.comment,
        "doi": r.doi,
    }


def _build_query(query: str, categories: list[str] | None) -> str:
    """Translate user-friendly inputs into arxiv's query DSL.

    `query` becomes ``all:<terms>``; categories become an OR-grouped
    ``cat:<cat>`` filter joined with AND.
    """
    parts = [f"all:{query}"]
    if categories:
        cat_clause = " OR ".join(f"cat:{c}" for c in categories)
        parts.append(f"({cat_clause})")
    return " AND ".join(parts)


# ---------------------------------------------------------------------------
# arxiv_search
# ---------------------------------------------------------------------------

# NOTE on rate-limiting: an earlier iteration (2026-05-16) added a
# process-wide ``asyncio.Lock()`` to serialize arxiv calls. It made things
# *worse* — the arxiv library already retries 3× with a 3 s built-in delay
# on 429s, so each call already takes 9+ s in the slow path; serializing N
# concurrent calls multiplies that by N and burns through pydantic-ai's
# request budget while accomplishing less. Now we let calls run in
# parallel; some will fail with HTTP 429, and the system prompt instructs
# the agent to pivot to ``web_search`` with ``site:arxiv.org`` as the
# fallback discovery path.


async def _arxiv_search(
    ctx: RunContext[PolymathState],
    query: Annotated[
        str,
        "Search query. Phrase like a user would, e.g. 'Koopman operator deep learning'.",
    ],
    max_results: Annotated[
        int,
        "Max results to return (1-50). Default 10.",
    ] = 10,
    categories: Annotated[
        list[str] | None,
        "Optional arxiv category filters, e.g. ['math.DS', 'cs.LG', 'eess.SY']. None = no filter.",
    ] = None,
    sort_by: Annotated[
        Literal["relevance", "lastUpdatedDate", "submittedDate"],
        "Sort order. 'relevance' is best for exploratory searches; "
        "'submittedDate' for the latest-first firehose.",
    ] = "relevance",
    days_back: Annotated[
        int | None,
        "If set, only include papers updated within the last N days. None = all time.",
    ] = None,
) -> str:
    """Search arxiv. Returns JSON list of papers with metadata + abstracts."""
    sid = ctx.deps.session_id
    await emit(
        sid,
        "tool.arxiv_search.started",
        {"query": query, "max_results": max_results, "categories": categories},
    )
    try:
        # Bound max_results to a sane ceiling
        max_results = max(1, min(50, max_results))
        client = arxiv.Client(page_size=min(max_results, 25), delay_seconds=3.0, num_retries=3)
        search = arxiv.Search(
            query=_build_query(query, categories),
            max_results=max_results,
            sort_by=_SORT_MAP[sort_by],
        )
        # arxiv.Client.results() is a generator that blocks on HTTP; thread it.
        results = await asyncio.to_thread(lambda: list(client.results(search)))

        if days_back is not None and days_back > 0:
            cutoff = datetime.now(timezone.utc).timestamp() - days_back * 86400
            results = [
                r for r in results
                if r.updated and r.updated.timestamp() >= cutoff
            ]

        payload = {
            "query": query,
            "categories": categories,
            "sort_by": sort_by,
            "n_results": len(results),
            "results": [_serialise_result(r) for r in results],
        }
    except Exception as exc:  # noqa: BLE001 — surface to agent as JSON error
        await emit(sid, "tool.arxiv_search.error", {"error": str(exc), "query": query})
        return json.dumps({"error": f"arxiv_search failed: {type(exc).__name__}: {exc}"})

    await emit(
        sid,
        "tool.arxiv_search.completed",
        {"query": query, "n_results": payload["n_results"]},
    )
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# arxiv_fetch
# ---------------------------------------------------------------------------

async def _arxiv_fetch(
    ctx: RunContext[PolymathState],
    arxiv_id: Annotated[
        str,
        "ArXiv ID (e.g. '2405.12345' or '2405.12345v2'). URLs are accepted and normalised.",
    ],
) -> str:
    """Fetch a single arxiv paper's metadata + abstract. Returns JSON."""
    sid = ctx.deps.session_id
    canonical_id = _normalise_arxiv_id(arxiv_id)
    await emit(sid, "tool.arxiv_fetch.started", {"arxiv_id": canonical_id})
    try:
        client = arxiv.Client(page_size=1, delay_seconds=3.0, num_retries=3)
        search = arxiv.Search(id_list=[canonical_id])
        results = await asyncio.to_thread(lambda: list(client.results(search)))
        if not results:
            await emit(
                sid,
                "tool.arxiv_fetch.error",
                {"arxiv_id": canonical_id, "error": "not found"},
            )
            return json.dumps({"error": f"arxiv_fetch: no paper with id {canonical_id!r}"})
        payload = _serialise_result(results[0])
    except Exception as exc:  # noqa: BLE001
        await emit(sid, "tool.arxiv_fetch.error", {"arxiv_id": canonical_id, "error": str(exc)})
        return json.dumps({"error": f"arxiv_fetch failed: {type(exc).__name__}: {exc}"})

    await emit(sid, "tool.arxiv_fetch.completed", {"arxiv_id": canonical_id})
    return json.dumps(payload, ensure_ascii=False)


arxiv_search = Tool(_arxiv_search, name="arxiv_search")
arxiv_fetch = Tool(_arxiv_fetch, name="arxiv_fetch")
