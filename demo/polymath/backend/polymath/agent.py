"""Backward-compat shim — the canonical orchestrator now lives in
:mod:`polymath.orchestrator` as a typed :class:`~orqest.agents.BaseAgent`
subclass.

Older callers may still import :func:`get_agent` from here; we re-export
the lazily-cached :class:`pydantic_ai.Agent` (lifted off the
:class:`PolymathAgent`'s ``agent`` property) so the legacy contract holds
without double-construction.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_ai import Agent

from polymath.orchestrator import PolymathAgent, get_polymath_agent
from polymath.state import PolymathState

# Re-exports — keep the public surface stable for any legacy imports.
__all__ = ["get_agent", "get_polymath_agent", "PolymathAgent"]


@lru_cache(maxsize=1)
def get_agent() -> Agent[PolymathState, str]:
    """Return the underlying ``pydantic_ai.Agent`` for backward compat.

    New code should prefer :func:`polymath.orchestrator.get_polymath_agent`,
    which returns the typed :class:`PolymathAgent` and exposes its
    underlying ``pydantic_ai.Agent`` via the :attr:`BaseAgent.agent`
    property — the same instance returned here.
    """
    return get_polymath_agent().agent
