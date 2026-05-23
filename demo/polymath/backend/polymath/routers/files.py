"""Read-only file endpoints for the frontend's Files + Editor tabs.

The agent's write path goes through the ``fs`` tools; these endpoints let
the UI browse the sandbox without an agent turn.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from polymath.sandbox.manager import SandboxError, get_manager

router = APIRouter(prefix="/sessions", tags=["files"])


@router.get("/{sid}/files")
async def list_files(
    sid: UUID,
    path: str = Query(default="", description="Directory relative to /workspace."),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Return a shallow directory listing for the session's sandbox."""
    try:
        rows, truncated = await get_manager().list_dir(str(sid), path, limit=limit)
    except SandboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": path, "entries": rows, "truncated": truncated}


@router.get("/{sid}/files/read")
async def read_file(
    sid: UUID,
    path: str = Query(..., description="File path relative to /workspace."),
    max_bytes: int = Query(default=200_000, ge=1, le=2_000_000),
) -> dict:
    """Return a text file's contents. Binary files return ``{binary: true}``."""
    try:
        data, truncated = await get_manager().get_file(str(sid), path, max_bytes=max_bytes)
    except SandboxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": path, "binary": True, "bytes": len(data)}
    return {"path": path, "text": text, "truncated": truncated}
