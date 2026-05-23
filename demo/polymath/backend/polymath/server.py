"""Polymath FastAPI application entrypoint.

Assembles routers, sets CORS, wires a startup hook that waits for
postgres and bootstraps tables, and exposes a ``/health`` endpoint that
validates the configured LLM model can be resolved.

See ``docs/PRINCIPLES.md`` — crash early, no import-time side effects.
The health endpoint returns ``degraded`` rather than crash-looping the
container when the model is unreachable.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orqest.utils.llm_model import resolve_model

from polymath.config import get_default_config
from polymath.db.session import init_db
from polymath.routers import (
    artifacts,
    autonomy,
    chat,
    config_router,
    events,
    files,
    memory,
    sessions,
    snapshot,
    tabs,
    takeover,
    ui,
    viewport,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Polymath", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(events.router)
app.include_router(snapshot.router)
app.include_router(files.router)
app.include_router(viewport.router)
app.include_router(artifacts.router)
app.include_router(takeover.router)
app.include_router(ui.router)
app.include_router(tabs.router)
app.include_router(memory.router)
app.include_router(autonomy.router)
app.include_router(config_router.router)


@app.on_event("startup")
async def _startup() -> None:
    """Bootstrap DB with backoff so we tolerate a slow postgres boot."""
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        # Log and continue — /health will report degraded state.
        logger.error("polymath: init_db failed at startup: %s", exc)


@app.get("/health")
async def health() -> dict:
    """Report service health.

    Returns ``{status: "ok"}`` when the configured model resolves cleanly,
    ``{status: "degraded", reason: ...}`` otherwise. This keeps docker
    healthchecks from crashlooping on missing API keys during setup.
    """
    cfg = get_default_config()
    try:
        resolve_model(cfg.LLM_MODEL, api_key=cfg.require_llm_key())
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "reason": str(exc), "model": cfg.LLM_MODEL}
    return {"status": "ok", "model": cfg.LLM_MODEL}
