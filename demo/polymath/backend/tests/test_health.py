"""Tests for `/health` — the lightweight liveness probe."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_reachable(client: AsyncClient) -> None:
    """Health never 5xx's — it returns ok or degraded."""
    r = await client.get("/health")
    assert r.status_code == 200  # Phase 0: any degraded status still returns 200.
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "model" in body


@pytest.mark.asyncio
async def test_health_degrades_without_api_key(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient, _frozen_config
) -> None:
    """When the LLM API key is missing, /health reports degraded — not 500."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("POLYMATH_LLM_API_KEY", raising=False)

    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert "LLM_API_KEY" in body["reason"]
