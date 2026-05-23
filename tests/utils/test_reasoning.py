import pytest
from pydantic_ai.settings import ModelSettings

from orqest.utils.reasoning import _EFFORT_BUDGET, resolve_reasoning_settings


class TestPerProviderTranslation:
    def test_openai_passthrough(self):
        settings = resolve_reasoning_settings("openai", "high")
        # `openai_reasoning_summary="auto"` is added so the Responses API
        # streams summary deltas back as ThinkingPart content; chat
        # completions silently ignores it.
        assert settings == {
            "openai_reasoning_effort": "high",
            "openai_reasoning_summary": "auto",
        }

    def test_openai_summary_default_auto(self):
        # Regression: without `openai_reasoning_summary`, the Responses
        # API runs reasoning server-side but emits an empty ThinkingPart,
        # which UI consumers render as "thought for 1 sec".
        settings = resolve_reasoning_settings("openai-responses", "medium")
        assert settings["openai_reasoning_summary"] == "auto"

    def test_openai_summary_respects_base_override(self):
        base = ModelSettings(openai_reasoning_summary="detailed")  # type: ignore[typeddict-unknown-key]
        settings = resolve_reasoning_settings("openai", "medium", base=base)
        # Caller's explicit choice wins — don't clobber.
        assert "openai_reasoning_summary" not in settings

    def test_anthropic_thinking_budget(self):
        settings = resolve_reasoning_settings("anthropic", "medium")
        assert settings["anthropic_thinking"] == {
            "type": "enabled",
            "budget_tokens": _EFFORT_BUDGET["medium"],
        }

    def test_google_thinking_config(self):
        settings = resolve_reasoning_settings("google", "low")
        assert settings["google_thinking_config"] == {
            "thinking_budget": _EFFORT_BUDGET["low"],
            "include_thoughts": True,
        }

    def test_openrouter_reasoning(self):
        settings = resolve_reasoning_settings("openrouter", "high")
        assert settings == {"openrouter_reasoning": {"effort": "high", "enabled": True}}

    def test_openrouter_minimal_collapses_to_low(self):
        # OpenRouter's effort literal has no "minimal".
        settings = resolve_reasoning_settings("openrouter", "minimal")
        assert settings["openrouter_reasoning"]["effort"] == "low"


class TestProviderNormalization:
    def test_provider_model_string_accepted(self):
        settings = resolve_reasoning_settings("anthropic:claude-sonnet-4-6", "low")
        assert "anthropic_thinking" in settings

    def test_google_gla_system_value_normalizes(self):
        # pydantic-ai's GoogleProvider.name is "google-gla", not "google".
        settings = resolve_reasoning_settings("google-gla", "low")
        assert "google_thinking_config" in settings


class TestMaxTokensHeadroom:
    def test_filled_when_base_lacks_max_tokens(self):
        settings = resolve_reasoning_settings("anthropic", "high")
        assert settings["max_tokens"] == _EFFORT_BUDGET["high"] + 8192

    def test_skipped_when_base_sets_max_tokens(self):
        base = ModelSettings(max_tokens=2000)
        settings = resolve_reasoning_settings("anthropic", "high", base=base)
        assert "max_tokens" not in settings

    def test_google_also_fills_headroom(self):
        settings = resolve_reasoning_settings("google", "medium")
        assert settings["max_tokens"] == _EFFORT_BUDGET["medium"] + 8192

    def test_openai_never_fills_max_tokens(self):
        # OpenAI is effort-based, not budget-based — no headroom concern.
        settings = resolve_reasoning_settings("openai", "high")
        assert "max_tokens" not in settings

    def test_base_is_not_mutated(self):
        base = ModelSettings(temperature=0.5)
        resolve_reasoning_settings("anthropic", "high", base=base)
        assert dict(base) == {"temperature": 0.5}


class TestValidation:
    def test_invalid_effort_raises(self):
        with pytest.raises(ValueError, match="Unknown reasoning effort"):
            resolve_reasoning_settings("openai", "extreme")  # type: ignore[arg-type]

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="not supported for provider"):
            resolve_reasoning_settings("cohere", "high")
