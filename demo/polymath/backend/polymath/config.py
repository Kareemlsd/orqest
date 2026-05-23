"""Polymath configuration — frozen, env-driven, lazy.

Mirrors Orqest's configuration discipline (see ``docs/concepts/config.md``):
a frozen dataclass so runtime values cannot mutate, and ``lru_cache`` on
the default loader so subsequent calls return the same instance.

Crash-early is enforced at *first use* rather than import time so the
FastAPI app can boot even when ``OPENAI_API_KEY`` is missing (health
endpoints degrade gracefully).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PolymathConfig:
    """Immutable runtime configuration for the Polymath backend."""

    LLM_MODEL: str
    LLM_API_KEY: str | None
    WEB_PROVIDER: str
    WEB_API_KEY: str | None
    DATABASE_URL: str
    MEMORY_DIR: Path
    USE_MCP: bool
    ENABLE_HEALING: bool = True
    """Wire :class:`~orqest.healing.HealingRunner` into per-session
    runtimes. Default-on for the demo so watchdogs (stall/loop) flow
    automatically; flip via ``POLYMATH_ENABLE_HEALING=0`` to opt out."""

    FALLBACK_MODELS: tuple[str, ...] = ()
    """Ordered ``provider:model_id`` chain for
    :func:`~orqest.healing.resolve_model_with_fallback`. Empty disables
    the fallback :class:`~pydantic_ai.models.Model`. Populate via
    ``POLYMATH_FALLBACK_MODELS=anthropic:claude-sonnet-4-6,openai:gpt-4.1``."""

    ENABLE_BROWSER: bool = False
    """Register the ``browser_*`` tools on the orchestrator and surface
    the noVNC ``BrowserTab`` in the frontend. Default-off — the
    Chromium + noVNC stack inside the sandbox is heavy. Flip via
    ``POLYMATH_ENABLE_BROWSER=1`` for demos that exercise browser
    automation."""

    ENABLE_SANDBOXED_HTML: bool = True
    """Allow the agent to emit
    :class:`~orqest.ui.SandboxedHTMLComponent` (Layer 3 generative-UI
    escape hatch) — raw HTML / SVG / restricted JS rendered inside an
    iframe with ``sandbox="allow-scripts"`` and a strict CSP
    (``default-src 'none'``). Default-on for the demo so the Canvas can
    showcase arbitrary agent-emitted visualisations the declarative
    grammars can't express; flip via ``POLYMATH_ENABLE_SANDBOXED_HTML=0``
    to lock the trust boundary back down."""

    ENABLE_SELF_RATING: bool = True
    """Run :class:`~orqest.metacognition.LLMSelfRatingProtocol` on each
    completed assistant turn so the chat surface can render a real
    per-message confidence badge. Costs +1 LLM call per turn (~$0.0001
    for small models). Default-on for the demo because the badge is the
    cognitive-backbone money shot; flip via
    ``POLYMATH_ENABLE_SELF_RATING=0`` to silence the badge and skip the
    extra call."""

    def require_llm_key(self) -> str:
        """Return ``LLM_API_KEY``, raising a clear error if unset.

        Called lazily from the agent/health paths so the rest of the app
        can import and boot without the key present (e.g. in CI).
        """
        if not self.LLM_API_KEY:
            raise ValueError(
                "LLM_API_KEY is not set. Export OPENAI_API_KEY (or the key "
                "matching POLYMATH_LLM_MODEL's provider) before starting "
                "the backend."
            )
        return self.LLM_API_KEY


def load_config() -> PolymathConfig:
    """Build a :class:`PolymathConfig` from environment variables.

    Env var order: prefer un-prefixed names (``LLM_MODEL``, ``DATABASE_URL``)
    set by docker-compose; fall back to ``POLYMATH_*`` for local dev without
    compose; finally to defaults.
    """
    memory_dir = Path(os.getenv("POLYMATH_MEMORY_DIR", "/data/memory"))
    llm_model = os.getenv("LLM_MODEL") or os.getenv("POLYMATH_LLM_MODEL", "openai:gpt-5.2")
    # Pick the provider-matching API key for common providers; otherwise fall
    # back to a generic POLYMATH_LLM_API_KEY.
    provider = llm_model.split(":", 1)[0] if ":" in llm_model else llm_model
    provider_key_map = {
        "openai": "OPENAI_API_KEY",
        # Responses API uses the same OpenAI credential.
        "openai-responses": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    api_key = os.getenv(provider_key_map.get(provider, ""), "") or os.getenv(
        "POLYMATH_LLM_API_KEY", ""
    ) or None

    fallback_raw = os.getenv("POLYMATH_FALLBACK_MODELS", "")
    fallback_models = tuple(
        spec.strip() for spec in fallback_raw.split(",") if spec.strip()
    )

    return PolymathConfig(
        LLM_MODEL=llm_model,
        LLM_API_KEY=api_key,
        WEB_PROVIDER=os.getenv("ORQEST_WEB_PROVIDER", "none"),
        WEB_API_KEY=os.getenv("ORQEST_WEB_API_KEY"),
        DATABASE_URL=os.getenv(
            "DATABASE_URL",
            os.getenv(
                "POLYMATH_DATABASE_URL",
                "postgresql+asyncpg://polymath:polymath@polymath-postgres:5432/polymath",
            ),
        ),
        MEMORY_DIR=memory_dir,
        USE_MCP=os.getenv("POLYMATH_USE_MCP", "0") == "1",
        ENABLE_HEALING=os.getenv("POLYMATH_ENABLE_HEALING", "1") == "1",
        FALLBACK_MODELS=fallback_models,
        ENABLE_BROWSER=os.getenv("POLYMATH_ENABLE_BROWSER", "0") == "1",
        ENABLE_SANDBOXED_HTML=os.getenv(
            "POLYMATH_ENABLE_SANDBOXED_HTML", "1"
        )
        == "1",
        ENABLE_SELF_RATING=os.getenv("POLYMATH_ENABLE_SELF_RATING", "1") == "1",
    )


@lru_cache(maxsize=1)
def get_default_config() -> PolymathConfig:
    """Return a cached :class:`PolymathConfig` built from env at first call."""
    return load_config()
