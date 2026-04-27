"""Session CRUD endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from polymath.db.models import Session
from polymath.db.session import get_sessionmaker
from polymath.routers.tabs import ensure_system_tab
from polymath.runtime import drop_runtime
from polymath.session_metrics import cumulative_for

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("")
async def create_session(body: dict | None = None) -> dict:
    """Create a new session row.

    Seeds the right-pane manifest with two open system tabs (Shell +
    Files) so a fresh session has an initial empty-state surface
    instead of a blank strip. Subsequent system tabs are spawned by the
    auto-respawn middleware on first relevant tool activity.
    """
    title = (body or {}).get("title") or "Untitled session"
    sm = get_sessionmaker()
    async with sm() as db:
        session = Session(title=title)
        db.add(session)
        await db.commit()
        await db.refresh(session)
    # Seed empty-state tabs. Failures swallowed — a session must come up
    # even if the bus / DB is briefly unhappy; auto-respawn will re-seed
    # them on first tool activity.
    try:
        await ensure_system_tab(session.id, "shell", title="Shell")
        await ensure_system_tab(session.id, "files", title="Files")
    except Exception:  # noqa: BLE001
        pass
    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat(),
    }


@router.get("")
async def list_sessions() -> dict:
    """List the 50 most recent sessions."""
    sm = get_sessionmaker()
    async with sm() as db:
        rows = (
            await db.execute(select(Session).order_by(Session.created_at.desc()).limit(50))
        ).scalars().all()
    return {
        "sessions": [
            {
                "id": str(r.id),
                "title": r.title,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/{sid}")
async def get_session(sid: UUID) -> dict:
    """Return session metadata + cumulative usage for the chrome's Context ring.

    ``cumulative_usage`` is a process-local snapshot maintained by
    :mod:`polymath.session_metrics`; it ticks up on every
    ``chat.turn.completed`` event. The frontend's session-header
    Context ring reads this once on mount, then patches via SSE.
    """
    sm = get_sessionmaker()
    async with sm() as db:
        session = await db.get(Session, sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "plan": {"tasks": []},
        "artifacts": [],
        "cumulative_usage": cumulative_for(str(sid)),
    }


@router.delete("/{sid}")
async def delete_session(sid: UUID) -> dict:
    """Delete a session row. Phase 2+ will also stop its sandbox."""
    sm = get_sessionmaker()
    async with sm() as db:
        session = await db.get(Session, sid)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        await db.delete(session)
        await db.commit()
    await drop_runtime(str(sid))
    # Best-effort: stop the session's sandbox + remove its workspace volume.
    try:
        from polymath.sandbox.manager import get_manager

        await get_manager().stop(str(sid), remove_volume=True)
    except Exception:  # noqa: BLE001 — tools/volumes not critical on delete.
        pass
    return {"ok": True, "id": str(sid)}
