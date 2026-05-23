"""Viewport URL endpoint.

Returns the URL the frontend should iframe to see the session's noVNC
stream. The URL points at the host port Docker assigned to the sandbox
container's ``:6080`` — the noVNC websockify-based HTTP proxy that
serves ``vnc.html`` + bridges WebSocket → VNC.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from polymath.runtime import get_runtime
from polymath.sandbox.manager import SandboxError, get_manager

router = APIRouter(prefix="/sessions", tags=["viewport"])


@router.get("/{sid}/viewport_url")
async def viewport_url(sid: UUID) -> dict:
    """Ensure the sandbox is running and return its noVNC URL.

    Frontend uses the returned ``url`` as the iframe src.
    Query-string options (``autoconnect``, ``resize=scale``, ``view_only``)
    are appended so the iframe boots straight into the desktop.
    """
    try:
        info = await get_manager().ensure(str(sid))
    except SandboxError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not info.novnc_port:
        raise HTTPException(status_code=503, detail="noVNC port not assigned")
    # Agent in control by default; Takeover flips view_only off.
    rt = get_runtime(str(sid))
    view_only = 0 if rt.takeover_active else 1
    url = (
        f"http://localhost:{info.novnc_port}/vnc.html"
        f"?autoconnect=1&resize=scale&view_only={view_only}"
    )
    return {
        "url": url,
        "novnc_port": info.novnc_port,
        "shell_port": info.shell_port,
        "view_only": bool(view_only),
        "takeover_active": rt.takeover_active,
    }
