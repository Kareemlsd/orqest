"""Artifact endpoints — list metadata, stream the underlying file."""

from __future__ import annotations

import mimetypes
from uuid import UUID

from fastapi import APIRouter, HTTPException
from starlette.responses import Response

from polymath.artifacts.store import get_artifact, list_artifacts
from polymath.sandbox.manager import SandboxError, get_manager

router = APIRouter(prefix="/sessions", tags=["artifacts"])


@router.get("/{sid}/artifacts")
async def list_for_session(sid: UUID) -> dict:
    rows = await list_artifacts(sid)
    return {
        "artifacts": [
            {
                "id": str(a.id),
                "kind": a.kind,
                "mime": a.mime,
                "label": a.label,
                "path": a.path,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ]
    }


@router.get("/{sid}/artifacts/{aid}")
async def download_artifact(sid: UUID, aid: UUID) -> Response:
    """Stream the artifact bytes out of the session's sandbox.

    We don't copy artifacts to the backend filesystem — they live in the
    sandbox volume and the backend proxies reads on demand. Keeps the
    per-session isolation boundary clean.
    """
    row = await get_artifact(aid)
    if row is None or str(row.session_id) != str(sid):
        raise HTTPException(status_code=404, detail="artifact not found")
    try:
        data, truncated = await get_manager().get_file(
            str(sid), row.path, max_bytes=50_000_000
        )
    except SandboxError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media = row.mime or (mimetypes.guess_type(row.path)[0] or "application/octet-stream")
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'inline; filename="{row.label or row.path.split("/")[-1]}"',
            "X-Polymath-Truncated": "1" if truncated else "0",
        },
    )
