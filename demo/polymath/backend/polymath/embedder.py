"""Optional OpenAI embeddings for ``LocalMemoryStore`` semantic recall.

When configured, this lets the agent's ``recall("Koopman scaling")`` query
fire a real cosine-similarity search over stored memory contents instead of
falling back to FTS5 LIKE matching (which is brittle for free-text concept
queries).

The embedder is **optional and gracefully degrading**:

* No ``OPENAI_API_KEY`` env var → :func:`maybe_make_embedder` returns ``None``,
  and ``LocalMemoryStore`` falls back to FTS5 LIKE. Nothing breaks.
* Key present but the embeddings call fails (network blip, rate limit) →
  the memory store logs at WARNING and the relevant write/recall degrades to
  the no-embedding path. The error never bubbles to the agent.

Default model: ``text-embedding-3-small`` (1536-dim, ~$0.02 per 1M tokens).
Cheap enough that a research session's memory writes cost fractions of a
cent. Override via ``POLYMATH_EMBEDDING_MODEL`` env var.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Awaitable

import httpx

_OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
_DEFAULT_MODEL = "text-embedding-3-small"


def _build_openai_embedder(
    api_key: str,
    model: str,
) -> Callable[[str], Awaitable[list[float]]]:
    """Return an async embedder callable suitable for ``LocalMemoryStore``."""

    async def _embed(text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _OPENAI_EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": text},
            )
            resp.raise_for_status()
            payload = resp.json()
        # OpenAI returns {"data": [{"embedding": [...]}], ...}
        return list(payload["data"][0]["embedding"])

    return _embed


def maybe_make_embedder() -> Callable[[str], Awaitable[list[float]]] | None:
    """Construct an embedder if ``OPENAI_API_KEY`` is in the environment.

    Returns ``None`` otherwise — callers should treat that as "no semantic
    recall available, fall back to FTS5 LIKE." ``LocalMemoryStore`` handles
    ``None`` natively.

    The model name is driven by ``POLYMATH_EMBEDDING_MODEL`` (default
    ``text-embedding-3-small``). Override only if you've benchmarked a
    different model on your domain.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    model = os.getenv("POLYMATH_EMBEDDING_MODEL", _DEFAULT_MODEL)
    return _build_openai_embedder(api_key, model)
