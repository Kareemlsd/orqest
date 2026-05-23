"""Tests for orqest.tools.web — graceful degradation + provider dispatch."""

from __future__ import annotations

import pytest
import httpx

from orqest.tools.web import (
    WebFetchResult,
    WebSearchResponse,
    WebSearchResult,
    web_fetch,
    web_search,
)


def _mock_transport(handler):
    """Build an httpx MockTransport from a handler function."""
    return httpx.MockTransport(handler)


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_disabled(self, monkeypatch):
        monkeypatch.delenv("ORQEST_WEB_API_KEY", raising=False)
        monkeypatch.setenv("ORQEST_WEB_PROVIDER", "tavily")

        resp = await web_search("what is k-omega sst")
        assert resp.disabled_reason == "ORQEST_WEB_API_KEY not set"
        assert resp.results == []
        assert resp.provider == "tavily"

    @pytest.mark.asyncio
    async def test_provider_none_returns_disabled(self, monkeypatch):
        monkeypatch.setenv("ORQEST_WEB_PROVIDER", "none")
        monkeypatch.setenv("ORQEST_WEB_API_KEY", "any")
        resp = await web_search("q")
        assert resp.disabled_reason == "provider disabled"
        assert resp.provider == "none"

    @pytest.mark.asyncio
    async def test_unknown_provider_returns_disabled(self, monkeypatch):
        monkeypatch.setenv("ORQEST_WEB_PROVIDER", "madeup")
        monkeypatch.setenv("ORQEST_WEB_API_KEY", "k")
        resp = await web_search("q")
        assert resp.disabled_reason is not None
        assert "unknown provider" in resp.disabled_reason


class TestProviderDispatch:
    @pytest.mark.asyncio
    async def test_tavily_payload_shape(self, monkeypatch):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content.decode()
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "k-omega SST model",
                            "url": "https://example.com/sst",
                            "content": "A two-equation turbulence model.",
                            "score": 0.9,
                        }
                    ]
                },
            )

        monkeypatch.setenv("ORQEST_WEB_PROVIDER", "tavily")
        monkeypatch.setenv("ORQEST_WEB_API_KEY", "key-123")

        # Patch httpx.AsyncClient to use our mock transport
        import orqest.tools.web as web_module

        orig = web_module.httpx.AsyncClient

        def patched_client(*args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            return orig(*args, **kwargs)

        monkeypatch.setattr(web_module.httpx, "AsyncClient", patched_client)

        resp = await web_search("sst turbulence", k=1)

        assert resp.provider == "tavily"
        assert len(resp.results) == 1
        assert resp.results[0].title == "k-omega SST model"
        assert resp.results[0].score == 0.9
        assert "tavily.com/search" in captured["url"]
        assert '"api_key":"key-123"' in captured["body"]

    @pytest.mark.asyncio
    async def test_brave_provider_selection(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("X-Subscription-Token") == "brave-key"
            return httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {"title": "T", "url": "https://a", "description": "D"}
                        ]
                    }
                },
            )

        monkeypatch.setenv("ORQEST_WEB_PROVIDER", "brave")
        monkeypatch.setenv("ORQEST_WEB_API_KEY", "brave-key")

        import orqest.tools.web as web_module

        orig = web_module.httpx.AsyncClient

        def patched_client(*args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            return orig(*args, **kwargs)

        monkeypatch.setattr(web_module.httpx, "AsyncClient", patched_client)

        resp = await web_search("q", k=1)
        assert resp.provider == "brave"
        assert resp.results[0].title == "T"


class TestWebFetch:
    @pytest.mark.asyncio
    async def test_happy_path_returns_text(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("user-agent") == "orqest-web-fetch/1.0"
            return httpx.Response(
                200,
                text="<html>hello world</html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

        import orqest.tools.web as web_module

        orig = web_module.httpx.AsyncClient

        def patched_client(*args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            return orig(*args, **kwargs)

        monkeypatch.setattr(web_module.httpx, "AsyncClient", patched_client)

        result = await web_fetch("https://example.com")
        assert isinstance(result, WebFetchResult)
        assert result.status_code == 200
        assert "hello world" in result.text
        assert result.content_type.startswith("text/html")
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_truncation(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, text="x" * 1000)

        import orqest.tools.web as web_module

        orig = web_module.httpx.AsyncClient

        def patched_client(*args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            return orig(*args, **kwargs)

        monkeypatch.setattr(web_module.httpx, "AsyncClient", patched_client)

        result = await web_fetch("https://example.com", max_chars=100)
        assert len(result.text) == 100
        assert result.truncated is True
