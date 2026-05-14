"""FastAPI route for the <NAME> agent.

Mount this router from your app's main router. Adjust the auth dependency
(``get_current_user``) and the response model to match the existing app
conventions.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from orqest.agents import GlobalState

# Replace these imports to match your app structure:
# from app.auth import get_current_user
# from app.config import settings

from .agent import build
from .types import <NAME>Output

router = APIRouter()


@router.post("/agents/<name>", response_model=<NAME>Output)
async def run_<name>(
    user=Depends(get_current_user),  # noqa: F821 — replace import per app
) -> <NAME>Output:
    """Invoke the <NAME> agent for the authenticated user."""
    agent = build(
        user_id=user.id,
        model=settings.llm_model,  # noqa: F821 — replace import per app
        api_key=settings.llm_api_key,  # noqa: F821
    )
    state = GlobalState()
    state.add_message("user", "<replace with the seed message or input shape>")
    return await agent.run(state)
