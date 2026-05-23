"""Citation graph tool — uses Semantic Scholar to find what cites a paper
and what a paper cites.

Wraps the ``semanticscholar`` package (Apache-2.0). Semantic Scholar's free
tier handles ~100 requests/minute without an API key; if a paid key is set
in the environment (``SEMANTIC_SCHOLAR_API_KEY``), it's used for higher
limits.

For research workflows this matters a lot — given one "anchor paper" the
agent finds, the citation graph surfaces:

* **Cites** (this paper's references) — what the authors built on; useful
  for tracing back to foundations.
* **Cited by** — what newer papers build on this; useful for finding the
  current frontier.

Returns metadata (title, authors, year, citation count, abstract excerpt)
rather than full text — keeps the response compact. The agent can drill
into individual papers via :func:`arxiv_fetch` or :func:`pdf_extract`.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Annotated, Literal

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool
from semanticscholar import SemanticScholar  # type: ignore[import-not-found]

from polymath.runtime import emit
from polymath.state import PolymathState
from polymath.tools.arxiv import _normalise_arxiv_id


def _client() -> SemanticScholar:
    """Build a SemanticScholar client with an API key if available.

    The free tier works without a key (lower rate limits); paid keys go in
    the ``SEMANTIC_SCHOLAR_API_KEY`` env var.
    """
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    return SemanticScholar(api_key=api_key, timeout=30)


def _summarise_paper(paper, abstract_chars: int = 400) -> dict:
    """Reduce a SemanticScholar paper object to JSON-safe metadata.

    Handles missing fields gracefully — the API returns sparse records for
    older / less-cited papers.
    """
    abstract = (paper.abstract or "")[:abstract_chars]
    if paper.abstract and len(paper.abstract) > abstract_chars:
        abstract += "…"
    authors: list[str] = []
    for author in (paper.authors or []):
        if author and getattr(author, "name", None):
            authors.append(author.name)
    external_ids = dict(paper.externalIds or {})
    arxiv_id = external_ids.get("ArXiv")
    return {
        "paper_id": paper.paperId,
        "title": (paper.title or "").strip(),
        "authors": authors,
        "year": paper.year,
        "venue": paper.venue,
        "citation_count": paper.citationCount,
        "abstract": abstract,
        "arxiv_id": arxiv_id,
        "doi": external_ids.get("DOI"),
        "url": paper.url,
    }


async def _citation_graph(
    ctx: RunContext[PolymathState],
    arxiv_id: Annotated[
        str,
        "ArXiv ID (e.g. '2405.12345') of the anchor paper. URLs are accepted "
        "and normalised. The paper must exist in Semantic Scholar's index.",
    ],
    direction: Annotated[
        Literal["cites", "cited_by", "both"],
        "'cites' = papers THIS paper cites (foundations); "
        "'cited_by' = papers that cite THIS paper (current frontier); "
        "'both' = both directions (default).",
    ] = "both",
    max_per_direction: Annotated[
        int,
        "Max papers to return per direction (1-50). Default 20.",
    ] = 20,
) -> str:
    """Fetch the citation graph of an arxiv paper via Semantic Scholar. Returns JSON."""
    sid = ctx.deps.session_id
    canonical_id = _normalise_arxiv_id(arxiv_id)
    # Drop version suffix if present — Semantic Scholar indexes by base id
    base_id = canonical_id.split("v")[0]
    paper_id = f"ARXIV:{base_id}"

    await emit(
        sid,
        "tool.citation_graph.started",
        {"arxiv_id": canonical_id, "direction": direction, "max": max_per_direction},
    )

    max_per_direction = max(1, min(50, max_per_direction))

    try:
        client = _client()
        # The anchor paper itself first
        anchor = await asyncio.to_thread(
            lambda: client.get_paper(paper_id),
        )
        if anchor is None:
            await emit(
                sid,
                "tool.citation_graph.error",
                {"arxiv_id": canonical_id, "error": "paper not in Semantic Scholar index"},
            )
            return json.dumps({
                "error": f"citation_graph: {canonical_id!r} not in Semantic Scholar's index"
            })

        payload: dict = {
            "paper": _summarise_paper(anchor, abstract_chars=600),
            "cites": [],
            "cited_by": [],
        }

        if direction in ("cites", "both"):
            refs = await asyncio.to_thread(
                lambda: client.get_paper_references(paper_id, limit=max_per_direction),
            )
            # Each ref is a wrapper; the actual cited paper is in .paper
            payload["cites"] = [
                _summarise_paper(r.paper) for r in refs if getattr(r, "paper", None)
            ]

        if direction in ("cited_by", "both"):
            citing = await asyncio.to_thread(
                lambda: client.get_paper_citations(paper_id, limit=max_per_direction),
            )
            payload["cited_by"] = [
                _summarise_paper(c.paper) for c in citing if getattr(c, "paper", None)
            ]

    except Exception as exc:  # noqa: BLE001
        await emit(
            sid,
            "tool.citation_graph.error",
            {"arxiv_id": canonical_id, "error": str(exc)},
        )
        return json.dumps({
            "error": f"citation_graph failed: {type(exc).__name__}: {exc}"
        })

    await emit(
        sid,
        "tool.citation_graph.completed",
        {
            "arxiv_id": canonical_id,
            "n_cites": len(payload["cites"]),
            "n_cited_by": len(payload["cited_by"]),
        },
    )
    return json.dumps(payload, ensure_ascii=False)


citation_graph = Tool(_citation_graph, name="citation_graph")
