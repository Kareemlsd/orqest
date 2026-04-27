"""Feature-flag endpoint — frontend reads this to conditionally render
heavyweight UI surfaces (currently: the noVNC browser tab).

The flags here mirror toggles in :class:`polymath.config.PolymathConfig`
that the frontend needs to know about. Backend-only flags (e.g. healing,
fallback model chain) stay invisible to the client.
"""

from __future__ import annotations

from fastapi import APIRouter

from polymath.config import get_default_config

router = APIRouter(tags=["config"])


@router.get("/config")
async def get_features() -> dict:
    """Return the active client-visible feature flags."""
    cfg = get_default_config()
    return {
        "features": {
            "browser": cfg.ENABLE_BROWSER,
            "healing": cfg.ENABLE_HEALING,
            "sandboxed_html": cfg.ENABLE_SANDBOXED_HTML,
        },
    }
