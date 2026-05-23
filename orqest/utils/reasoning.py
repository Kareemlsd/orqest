"""Provider-agnostic reasoning/thinking effort for pydantic-ai models.

pydantic-ai exposes thinking through a different provider-specific
``ModelSettings`` key for every provider — ``anthropic_thinking``,
``openai_reasoning_effort``, ``google_thinking_config``,
``openrouter_reasoning``. This module collapses that into one knob: a
:data:`ReasoningEffort` level that orqest translates into the right
provider-specific setting, keyed off the same provider prefix that
:func:`~orqest.utils.llm_model.resolve_model` already understands.

Adding a provider means adding one entry to ``_TRANSLATORS`` — no
control-flow edits — mirroring the registry pattern in ``llm_model.py``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic_ai.settings import ModelSettings

ReasoningEffort = Literal["minimal", "low", "medium", "high"]

_VALID_EFFORTS: tuple[ReasoningEffort, ...] = ("minimal", "low", "medium", "high")

# Effort → thinking-token budget, for providers that take a numeric
# budget rather than a categorical level (Anthropic, Google).
_EFFORT_BUDGET: dict[ReasoningEffort, int] = {
    "minimal": 1024,  # Anthropic's documented minimum budget_tokens
    "low": 4096,
    "medium": 12288,
    "high": 24576,
}

# Headroom added on top of a thinking budget when the caller did not set
# max_tokens. Anthropic *requires* max_tokens > budget_tokens, so
# reasoning would fail out of the box on that provider without this.
_OUTPUT_HEADROOM = 8192


def _openai(effort: ReasoningEffort, base: ModelSettings) -> dict:
    # OpenAI's reasoning_effort literal is categorical — direct passthrough.
    # `openai_reasoning_summary` only matters on the Responses API path
    # (``openai-responses:`` model prefix); chat-completions silently
    # ignores it. Without ``summary``, the Responses API runs reasoning
    # server-side but doesn't stream summary deltas — pydantic-ai then
    # emits an empty ThinkingPart and UI consumers (e.g. the Vercel
    # AI SDK's `<Reasoning />`) render "thought for 1 sec" with no
    # content. ``auto`` lets OpenAI pick concise/detailed per model.
    settings: dict = {"openai_reasoning_effort": effort}
    if "openai_reasoning_summary" not in base:
        settings["openai_reasoning_summary"] = "auto"
    return settings


def _anthropic(effort: ReasoningEffort, base: ModelSettings) -> dict:
    budget = _EFFORT_BUDGET[effort]
    settings: dict = {
        "anthropic_thinking": {"type": "enabled", "budget_tokens": budget},
    }
    if base.get("max_tokens") is None:
        settings["max_tokens"] = budget + _OUTPUT_HEADROOM
    return settings


def _google(effort: ReasoningEffort, base: ModelSettings) -> dict:
    budget = _EFFORT_BUDGET[effort]
    settings: dict = {
        "google_thinking_config": {
            "thinking_budget": budget,
            "include_thoughts": True,
        },
    }
    if base.get("max_tokens") is None:
        settings["max_tokens"] = budget + _OUTPUT_HEADROOM
    return settings


def _openrouter(effort: ReasoningEffort, base: ModelSettings) -> dict:
    # OpenRouter's effort literal has no "minimal" — collapse it to "low".
    or_effort = "low" if effort == "minimal" else effort
    return {"openrouter_reasoning": {"effort": or_effort, "enabled": True}}


_TRANSLATORS: dict[str, Callable[[ReasoningEffort, ModelSettings], dict]] = {
    "openai": _openai,
    "anthropic": _anthropic,
    "google": _google,
    "openrouter": _openrouter,
}


def resolve_reasoning_settings(
    provider: str,
    effort: ReasoningEffort,
    *,
    base: ModelSettings | None = None,
) -> dict:
    """Translate a unified :data:`ReasoningEffort` into provider-specific settings.

    Args:
        provider: A provider prefix (``'openai'``, ``'anthropic'``, …), a
            ``'provider:model_id'`` string, or a pydantic-ai ``Model.system``
            value (e.g. ``'google-gla'``). Only the provider segment is used.
        effort: One of ``'minimal'`` | ``'low'`` | ``'medium'`` | ``'high'``.
        base: Existing ``ModelSettings``, consulted (never mutated) so the
            translator can avoid clobbering an explicit ``max_tokens``.

    Returns:
        A dict of provider-specific ``ModelSettings`` keys to merge into the
        agent's ``model_settings``.

    Raises:
        ValueError: If ``effort`` is invalid or the provider is unknown.

    """
    if effort not in _VALID_EFFORTS:
        raise ValueError(
            f"Unknown reasoning effort {effort!r}. "
            f"Valid: {', '.join(_VALID_EFFORTS)}."
        )

    # Accept 'provider:model', 'google-gla', or a bare prefix — all collapse
    # to the registry key (e.g. 'google-gla' / 'google:gemini-pro' → 'google').
    key = provider.split(":", 1)[0].split("-", 1)[0]
    translator = _TRANSLATORS.get(key)
    if translator is None:
        supported = ", ".join(sorted(_TRANSLATORS))
        raise ValueError(
            f"Reasoning is not supported for provider {key!r}. "
            f"Supported: {supported}."
        )

    return translator(effort, base or {})
