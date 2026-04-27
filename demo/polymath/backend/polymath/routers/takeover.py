"""Takeover endpoints — pause/resume the agent and grant the user
interactive control of the sandbox viewport.

Takeover is a *trust affordance*. The agent is request-driven (not a
background loop) so "pause" semantically means: while the flag is set,
the chat router rejects new turns (409) and the viewport iframe is
served with ``view_only=0`` so the user can click and type into the
sandbox Chromium directly.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from polymath.runtime import emit, get_runtime

router = APIRouter(prefix="/sessions", tags=["takeover"])


@router.get("/{sid}/takeover")
async def get_takeover(sid: UUID) -> dict:
    rt = get_runtime(str(sid))
    return {"active": rt.takeover_active}


@router.post("/{sid}/takeover")
async def activate(sid: UUID) -> dict:
    rt = get_runtime(str(sid))
    rt.takeover_active = True
    await emit(str(sid), "takeover.activated", {})
    return {"active": True}


@router.post("/{sid}/resume")
async def release(sid: UUID) -> dict:
    rt = get_runtime(str(sid))
    rt.takeover_active = False
    await emit(str(sid), "takeover.released", {})
    return {"active": False}
