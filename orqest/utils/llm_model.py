"""Model resolution for pydantic-ai.

Translates a 'provider:model_name' string and an API key into a ready-to-use
pydantic-ai Model instance. Provider routing uses a registry dict so adding a
new provider means adding one entry, not editing control flow.
"""
from __future__ import annotations

from pydantic_ai.models import Model


def _build_registry() -> dict[str, tuple[type, type]]:
    """Lazily import provider classes and return the registry.

    Imports are deferred so the module has no import-time side effects beyond
    defining names, and so users only pay for the providers they actually use.
    """
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.providers.anthropic import AnthropicProvider
    from pydantic_ai.providers.google import GoogleProvider
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    return {
        "openai": (OpenAIChatModel, OpenAIProvider),
        "anthropic": (AnthropicModel, AnthropicProvider),
        "google": (GoogleModel, GoogleProvider),
        "openrouter": (OpenRouterModel, OpenRouterProvider),
    }


def resolve_model(model_name: str, *, api_key: str) -> Model:
    """Resolve a 'provider:model_id' string into a pydantic-ai Model.

    Args:
        model_name: In 'provider:model_id' format (e.g. 'openai:gpt-4o').
        api_key: API key passed to the provider constructor.

    Raises:
        ValueError: If the format is invalid or the provider is unknown.
    """
    if ":" not in model_name:
        raise ValueError(
            f"Model name {model_name!r} must use 'provider:model_id' format "
            f"(e.g., 'openai:gpt-4o'). Update your LLM_MODEL environment variable."
        )

    provider_prefix, model_id = model_name.split(":", maxsplit=1)
    if not model_id:
        raise ValueError(
            f"Model name {model_name!r} has an empty model ID after the colon."
        )

    registry = _build_registry()
    entry = registry.get(provider_prefix)
    if entry is None:
        supported = ", ".join(sorted(registry))
        raise ValueError(
            f"Unknown provider {provider_prefix!r} in {model_name!r}. "
            f"Supported: {supported}"
        )

    model_cls, provider_cls = entry
    return model_cls(model_name=model_id, provider=provider_cls(api_key=api_key))
