"""Config loading + env-var precedence + crash-early semantics."""

from __future__ import annotations

import pytest


def _reload_config_module():
    """Clear the lru_cache so the next load_config() reads fresh env."""
    from polymath import config as cfg_mod

    cfg_mod.get_default_config.cache_clear()
    return cfg_mod


def test_llm_model_env_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_MODEL (unprefixed) wins over POLYMATH_LLM_MODEL."""
    monkeypatch.setenv("LLM_MODEL", "anthropic:claude-sonnet-4")
    monkeypatch.setenv("POLYMATH_LLM_MODEL", "openai:gpt-4.1")
    cfg = _reload_config_module().load_config()
    assert cfg.LLM_MODEL == "anthropic:claude-sonnet-4"


def test_api_key_routes_by_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic model pulls ANTHROPIC_API_KEY, not OPENAI_API_KEY."""
    monkeypatch.setenv("LLM_MODEL", "anthropic:claude-sonnet-4")
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an")
    cfg = _reload_config_module().load_config()
    assert cfg.LLM_API_KEY == "an"


def test_api_key_falls_back_to_polymath_llm_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown provider falls through to POLYMATH_LLM_API_KEY."""
    monkeypatch.setenv("LLM_MODEL", "unknown:foo-1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("POLYMATH_LLM_API_KEY", "fallback-key")
    cfg = _reload_config_module().load_config()
    assert cfg.LLM_API_KEY == "fallback-key"


def test_require_llm_key_crashes_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL", "openai:gpt-4.1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("POLYMATH_LLM_API_KEY", raising=False)
    cfg = _reload_config_module().load_config()
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        cfg.require_llm_key()


def test_require_llm_key_returns_value_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL", "openai:gpt-4.1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = _reload_config_module().load_config()
    assert cfg.require_llm_key() == "sk-test"


def test_mcp_toggle_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLYMATH_USE_MCP", "1")
    cfg = _reload_config_module().load_config()
    assert cfg.USE_MCP is True
    monkeypatch.setenv("POLYMATH_USE_MCP", "0")
    cfg = _reload_config_module().load_config()
    assert cfg.USE_MCP is False


def test_database_url_default_contains_asyncpg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DATABASE_URL is unset, default includes an async driver prefix."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POLYMATH_DATABASE_URL", raising=False)
    cfg = _reload_config_module().load_config()
    assert "asyncpg" in cfg.DATABASE_URL or "aiosqlite" in cfg.DATABASE_URL
