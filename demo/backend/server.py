"""Orqest demo backend — FastAPI app that mounts all demo routers.

Each demo lives in demo/backend/demos/{name}.py and exposes a
POST /api/demos/{name}/chat endpoint via VercelAIAdapter.

Run: cd ~/repos/orqest && PYTHONPATH=. .venv/bin/uvicorn demo.backend.server:app --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI

from demo.backend._config import MODEL
from demo.backend.demos import artifact, chat, multimodal, research, tasks
from demo.backend.workbench.router import router as workbench_router

app = FastAPI(title="Orqest Demo")

app.include_router(chat.router)
app.include_router(artifact.router)
app.include_router(tasks.router)
app.include_router(multimodal.router)
app.include_router(research.router)
app.include_router(workbench_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok", "framework": "orqest", "model": MODEL}
