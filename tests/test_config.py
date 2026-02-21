import pytest

from orqest.config import OrqestConfig, load_config, get_default_config


class TestOrqestConfig:
    def test_frozen(self, test_config):
        with pytest.raises(AttributeError):
            test_config.llm_api_key = "new-key"

    def test_fields(self, test_config):
        assert test_config.llm_api_key == "test-key-123"
        assert test_config.llm_model == "openai:gpt-3.5-turbo"
        assert test_config.embedding_model == "all-MiniLM-L6-v2"
        assert test_config.embedding_api_key == "test-key-123"


class TestLoadConfig:
    def test_loads_with_api_key(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "my-key")
        monkeypatch.setenv("LLM_MODEL", "anthropic:claude-3.5-sonnet")
        config = load_config()
        assert config.llm_api_key == "my-key"
        assert config.llm_model == "anthropic:claude-3.5-sonnet"

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            load_config()

    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        config = load_config()
        assert config.llm_model == "openai:gpt-3.5-turbo"
        assert config.embedding_model == "all-MiniLM-L6-v2"

    def test_embedding_api_key_falls_back_to_llm_key(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "shared-key")
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        config = load_config()
        assert config.embedding_api_key == "shared-key"

    def test_embedding_api_key_independent(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "llm-key")
        monkeypatch.setenv("EMBEDDING_API_KEY", "embed-key")
        config = load_config()
        assert config.embedding_api_key == "embed-key"


class TestGetDefaultConfig:
    def test_returns_config(self, monkeypatch):
        # Clear the lru_cache so this test is isolated
        get_default_config.cache_clear()
        monkeypatch.setenv("LLM_API_KEY", "cached-key")
        config = get_default_config()
        assert config.llm_api_key == "cached-key"
        get_default_config.cache_clear()

    def test_caches_result(self, monkeypatch):
        get_default_config.cache_clear()
        monkeypatch.setenv("LLM_API_KEY", "cached-key")
        first = get_default_config()
        second = get_default_config()
        assert first is second
        get_default_config.cache_clear()
