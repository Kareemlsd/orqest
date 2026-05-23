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
    defining names. Providers that fail to import (e.g. due to missing or
    incompatible SDK versions) are skipped and raise at resolve_model() time
    only if actually requested — defensive belt-and-suspenders, since the
    full ``pydantic-ai`` dependency already bundles every provider SDK.
    """
    import logging

    logger = logging.getLogger(__name__)

    registry: dict[str, tuple[type, type]] = {}

    try:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        registry["openai"] = (OpenAIChatModel, OpenAIProvider)
    except ImportError:
        logger.debug("OpenAI provider unavailable, skipping")

    try:
        from pydantic_ai.models.openai import OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        # OpenAI Responses API path — required for gpt-5* + function tools +
        # reasoning_effort. The chat/completions path rejects that combo and
        # also tends to desynchronize tool_call/tool message pairs after a
        # ContextManager-driven summarization (observed in Polymath 2026-05-16).
        registry["openai-responses"] = (OpenAIResponsesModel, OpenAIProvider)
    except ImportError:
        logger.debug("OpenAI Responses provider unavailable, skipping")

    try:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        registry["anthropic"] = (AnthropicModel, AnthropicProvider)
    except ImportError:
        logger.debug("Anthropic provider unavailable, skipping")

    try:
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        registry["google"] = (GoogleModel, GoogleProvider)
    except ImportError:
        logger.debug("Google provider unavailable, skipping")

    try:
        from pydantic_ai.models.openrouter import OpenRouterModel
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        registry["openrouter"] = (OpenRouterModel, OpenRouterProvider)
    except ImportError:
        logger.debug("OpenRouter provider unavailable, skipping")

    return registry


def resolve_model(model_name: str, *, api_key: str) -> Model:
    """Resolve a 'provider:model_id' string into a pydantic-ai Model.

    Args:
        model_name: In 'provider:model_id' format (e.g. 'openai:gpt-4.1').
        api_key: API key passed to the provider constructor.

    Raises:
        ValueError: If the format is invalid or the provider is unknown.
    """
    if ":" not in model_name:
        raise ValueError(
            f"Model name {model_name!r} must use 'provider:model_id' format "
            f"(e.g., 'openai:gpt-4.1'). Update your LLM_MODEL environment variable."
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
