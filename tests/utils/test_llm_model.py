import pytest
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel

from orqest.utils.llm_model import resolve_model


class TestResolveModel:
    def test_openai(self):
        m = resolve_model("openai:gpt-4o", api_key="k")
        assert isinstance(m, OpenAIChatModel)

    def test_anthropic(self):
        m = resolve_model("anthropic:claude-3.5-sonnet", api_key="k")
        assert isinstance(m, AnthropicModel)

    def test_google(self):
        m = resolve_model("google:gemini-pro", api_key="k")
        assert isinstance(m, GoogleModel)

    def test_openrouter(self):
        m = resolve_model("openrouter:anthropic/claude-3.5-sonnet", api_key="k")
        assert isinstance(m, OpenRouterModel)

    def test_returns_model_base(self):
        m = resolve_model("openai:gpt-4o", api_key="k")
        assert isinstance(m, Model)

    def test_missing_colon_raises(self):
        with pytest.raises(ValueError, match="provider:model_id"):
            resolve_model("gpt-4o", api_key="k")

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            resolve_model("unknown:model-x", api_key="k")

    def test_empty_model_id_raises(self):
        with pytest.raises(ValueError, match="empty model ID"):
            resolve_model("openai:", api_key="k")
