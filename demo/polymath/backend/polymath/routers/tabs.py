"""Tab manifest endpoints — the unified right-pane is driven from here.

The frontend's ``useTabs`` hook hydrates from ``GET /sessions/{sid}/tabs`` on
mount, then live-merges ``tab.*`` SSE events from the shared
``SidecarProvider``. Every mutation writes to Postgres *and* publishes a
matching event on the session's ``Workbench.event_bus`` so the manifest
stays coherent across reload boundaries and across tabs of the same
session in different browser windows.

Closure is soft: ``DELETE`` flips ``status='closed'`` and stamps
``closed_at``; the row stays in the DB so a "recently closed" surface can
restore it. The list endpoint includes tombstones within a 24-hour window
(filterable via ``?include_closed=false`` for clients that only want the
live strip).

The router is deliberately bus-aware but otherwise stateless — system
runtime hooks (auto-respawn, etc.) emit the same ``tab.opened`` /
``tab.updated`` events directly via :func:`_emit` so the frontend never has
to distinguish "agent opened a tab" from "user opened a tab" from "system
auto-spawned a tab".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from orqest.observability import AgentEvent

from polymath.db.models import Session, Tab
from polymath.db.session import get_sessionmaker

router = APIRouter(prefix="/sessions", tags=["tabs"])


# ---- helpers -----------------------------------------------------------


_TOMBSTONE_TTL = timedelta(hours=24)
_VALID_KINDS: tuple[str, ...] = (
    "shell",
    "files",
    "browser",
    "editor",
    "chart_gallery",
    "report",
    "memory",
    "agents",
    "component",
)
_SYSTEM_KINDS = frozenset(_VALID_KINDS) - {"component"}


async def _emit(session_id: UUID, event_type: str, data: dict[str, Any]) -> None:
    """Publish a ``tab.*`` event on the session's bus.

    Best-effort: bus emission failures are swallowed (the SSE handler logs).
    The persisted row is the source of truth — losing the event only
    delays propagation until the next refresh / reload.

    Imported lazily to break the cycle ``workbench_factory →
    tab_respawn → routers.tabs → runtime → workbench_factory``.
    """
    # Local import: see docstring.
    from polymath.runtime import get_runtime

    runtime = get_runtime(str(session_id))
    await runtime.workbench.event_bus.emit(
        AgentEvent(
            event_type=event_type,
            agent_name=f"polymath[{session_id}]",
            timestamp=datetime.now(UTC),
            data=data,
        )
    )


def _serialize(tab: Tab) -> dict[str, Any]:
    """Project a :class:`Tab` row to the JSON shape the frontend consumes."""
    return {
        "id": str(tab.id),
        "session_id": str(tab.session_id),
        "kind": tab.kind,
        "title": tab.title,
        "position": tab.position,
        "pinned": tab.pinned,
        "status": tab.status,
        "content_ref": dict(tab.content_ref or {}),
        "metadata": dict(tab.metadata_json or {}),
        "created_at": tab.created_at.isoformat(),
        "updated_at": tab.updated_at.isoformat(),
        "last_activity_at": tab.last_activity_at.isoformat(),
        "closed_at": tab.closed_at.isoformat() if tab.closed_at else None,
    }


def _utc_now_naive() -> datetime:
    """Naive UTC datetime — matches the column convention in :mod:`db.models`."""
    return datetime.now(UTC).replace(tzinfo=None)


# ---- request shapes ----------------------------------------------------


class TabCreate(BaseModel):
    """Body for ``POST /sessions/{sid}/tabs``.

    ``id`` is optional and lets the agent (or system code) supply a stable
    UUID for idempotent creation — calling twice with the same id no-ops.
    """

    id: UUID | None = None
    kind: Literal[
        "shell",
        "files",
        "browser",
        "editor",
        "chart_gallery",
        "report",
        "memory",
        "agents",
        "component",
    ]
    title: str = Field(min_length=1, max_length=120)
    position: int | None = None
    pinned: bool = False
    content_ref: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TabPatch(BaseModel):
    """Body for ``PATCH /sessions/{sid}/tabs/{tab_id}``."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    position: int | None = None
    pinned: bool | None = None
    status: Literal["open", "closed"] | None = None
    content_ref: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    last_activity_at: datetime | None = None


class TabReorder(BaseModel):
    """Body for ``POST /sessions/{sid}/tabs/reorder``."""

    order: list[UUID]


# ---- endpoints ---------------------------------------------------------


@router.get("/{sid}/tabs")
async def list_tabs(sid: UUID, include_closed: bool = True) -> dict:
    """Return the manifest, ordered by ``position``.

    Open tabs always come back. Tombstoned (``status='closed'``) rows are
    included by default but only within a 24-hour TTL so the "recently
    closed" surface stays bounded.
    """
    sm = get_sessionmaker()
    cutoff = _utc_now_naive() - _TOMBSTONE_TTL
    async with sm() as db:
        stmt = (
            select(Tab)
            .where(Tab.session_id == sid)
            .order_by(Tab.position.asc(), Tab.created_at.asc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        active = await db.get(Session, sid)
    visible: list[Tab] = []
    for r in rows:
        if r.status == "open":
            visible.append(r)
        elif include_closed and r.closed_at and r.closed_at >= cutoff:
            visible.append(r)
    return {
        "tabs": [_serialize(r) for r in visible],
        "active_tab_id": str(active.active_tab_id)
        if active and active.active_tab_id
        else None,
    }


@router.post("/{sid}/tabs")
async def create_tab(sid: UUID, body: TabCreate) -> dict:
    """Open a new tab.

    Idempotent on ``body.id`` — POSTing twice with the same id returns the
    existing row without re-emitting the open event. New ids get a fresh
    row and a ``tab.opened`` event.
    """
    sm = get_sessionmaker()
    now = _utc_now_naive()
    async with sm() as db:
        # Idempotency on client-supplied id.
        if body.id is not None:
            existing = await db.get(Tab, body.id)
            if existing is not None and existing.session_id == sid:
                return _serialize(existing)
        # Default position: end of the strip.
        if body.position is None:
            stmt = select(Tab.position).where(
                Tab.session_id == sid, Tab.status == "open"
            )
            existing_positions = [
                p for p in (await db.execute(stmt)).scalars().all() if p is not None
            ]
            position = (max(existing_positions) + 1) if existing_positions else 0
        else:
            position = body.position
        tab = Tab(
            id=body.id or uuid4(),
            session_id=sid,
            kind=body.kind,
            title=body.title,
            position=position,
            pinned=body.pinned,
            status="open",
            content_ref=body.content_ref,
            metadata_json=body.metadata,
            created_at=now,
            updated_at=now,
            last_activity_at=now,
        )
        db.add(tab)
        await db.commit()
        await db.refresh(tab)
    payload = _serialize(tab)
    await _emit(sid, "tab.opened", payload)
    return payload


@router.patch("/{sid}/tabs/{tab_id}")
async def patch_tab(sid: UUID, tab_id: UUID, body: TabPatch) -> dict:
    """Update tab fields. Always bumps ``updated_at``.

    Status transitions go through this endpoint, but ``DELETE`` is the
    canonical close path — sending ``status='closed'`` here also stamps
    ``closed_at`` for tombstone-window tracking.
    """
    sm = get_sessionmaker()
    now = _utc_now_naive()
    async with sm() as db:
        tab = await db.get(Tab, tab_id)
        if tab is None or tab.session_id != sid:
            raise HTTPException(status_code=404, detail="tab not found")
        changed = False
        if body.title is not None and body.title != tab.title:
            tab.title = body.title
            changed = True
        if body.position is not None and body.position != tab.position:
            tab.position = body.position
            changed = True
        if body.pinned is not None and body.pinned != tab.pinned:
            tab.pinned = body.pinned
            changed = True
        if body.status is not None and body.status != tab.status:
            tab.status = body.status
            tab.closed_at = now if body.status == "closed" else None
            changed = True
        if body.content_ref is not None:
            tab.content_ref = body.content_ref
            changed = True
        if body.metadata is not None:
            tab.metadata_json = body.metadata
            changed = True
        if body.last_activity_at is not None:
            # Strip tz to match column convention (TIMESTAMP WITHOUT TIME ZONE).
            tab.last_activity_at = body.last_activity_at.replace(tzinfo=None)
            changed = True
        if changed:
            tab.updated_at = now
            db.add(tab)
            await db.commit()
            await db.refresh(tab)
    payload = _serialize(tab)
    await _emit(sid, "tab.updated", payload)
    return payload


@router.delete("/{sid}/tabs/{tab_id}")
async def close_tab(sid: UUID, tab_id: UUID) -> dict:
    """Soft-close — flips ``status='closed'``, stamps ``closed_at``.

    Restorable via ``POST .../tabs/{tab_id}/restore`` for the next 24 hours.
    """
    sm = get_sessionmaker()
    now = _utc_now_naive()
    async with sm() as db:
        tab = await db.get(Tab, tab_id)
        if tab is None or tab.session_id != sid:
            raise HTTPException(status_code=404, detail="tab not found")
        if tab.status != "closed":
            tab.status = "closed"
            tab.closed_at = now
            tab.updated_at = now
            db.add(tab)
        # If the active tab was just closed, clear the pointer so the
        # frontend can fall back to the next open tab on rehydrate.
        sess = await db.get(Session, sid)
        if sess is not None and sess.active_tab_id == tab.id:
            sess.active_tab_id = None
            db.add(sess)
        await db.commit()
        await db.refresh(tab)
    payload = _serialize(tab)
    await _emit(sid, "tab.closed", payload)
    return payload


@router.post("/{sid}/tabs/{tab_id}/restore")
async def restore_tab(sid: UUID, tab_id: UUID) -> dict:
    """Un-tombstone a closed tab. 404 if older than 24 h or never closed."""
    sm = get_sessionmaker()
    now = _utc_now_naive()
    cutoff = now - _TOMBSTONE_TTL
    async with sm() as db:
        tab = await db.get(Tab, tab_id)
        if tab is None or tab.session_id != sid:
            raise HTTPException(status_code=404, detail="tab not found")
        if tab.status != "closed" or tab.closed_at is None:
            raise HTTPException(status_code=409, detail="tab is not closed")
        if tab.closed_at < cutoff:
            raise HTTPException(status_code=410, detail="tab tombstone expired")
        tab.status = "open"
        tab.closed_at = None
        tab.updated_at = now
        tab.last_activity_at = now
        db.add(tab)
        await db.commit()
        await db.refresh(tab)
    payload = _serialize(tab)
    await _emit(sid, "tab.restored", payload)
    return payload


@router.post("/{sid}/tabs/reorder")
async def reorder_tabs(sid: UUID, body: TabReorder) -> dict:
    """Apply a bulk position update in one transaction.

    ``body.order`` is the new sequence of tab ids; positions are written
    as their index in the list. Tabs not present in ``order`` keep their
    existing position (lets the frontend reorder a subset without having
    to enumerate the whole strip).
    """
    sm = get_sessionmaker()
    now = _utc_now_naive()
    async with sm() as db:
        ids = list(body.order)
        if not ids:
            return {"ok": True, "updated": 0}
        stmt = select(Tab).where(Tab.session_id == sid, Tab.id.in_(ids))
        rows = {r.id: r for r in (await db.execute(stmt)).scalars().all()}
        updated: list[Tab] = []
        for index, tid in enumerate(ids):
            tab = rows.get(tid)
            if tab is None:
                continue
            if tab.position != index:
                tab.position = index
                tab.updated_at = now
                db.add(tab)
                updated.append(tab)
        await db.commit()
        for r in updated:
            await db.refresh(r)
    for r in updated:
        await _emit(sid, "tab.updated", _serialize(r))
    return {"ok": True, "updated": len(updated)}


@router.post("/{sid}/tabs/{tab_id}/focus")
async def focus_tab(sid: UUID, tab_id: UUID) -> dict:
    """Set the session's active tab.

    Persists ``Session.active_tab_id`` and emits ``tab.focused`` so other
    open browser tabs of the same session sync up. The frontend uses the
    5 s user-click lockout to suppress the heuristic — but explicit calls
    here always win.
    """
    sm = get_sessionmaker()
    now = _utc_now_naive()
    async with sm() as db:
        tab = await db.get(Tab, tab_id)
        if tab is None or tab.session_id != sid:
            raise HTTPException(status_code=404, detail="tab not found")
        if tab.status != "open":
            raise HTTPException(status_code=409, detail="cannot focus a closed tab")
        sess = await db.get(Session, sid)
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")
        sess.active_tab_id = tab.id
        tab.last_activity_at = now
        db.add(sess)
        db.add(tab)
        await db.commit()
        await db.refresh(tab)
    payload = _serialize(tab)
    await _emit(sid, "tab.focused", payload)
    return payload


# ---- helpers used by other backend modules -----------------------------


async def ensure_system_tab(
    sid: UUID,
    kind: str,
    *,
    title: str,
    content_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent system-tab creation.

    Used by the auto-respawn middleware and by ``routers/sessions.py`` to
    seed the initial Shell + Files tabs. Looks up the latest **open** tab
    matching ``(session_id, kind, content_ref->>'path' if applicable)``
    and reuses it. Otherwise creates a new row and emits ``tab.opened``.

    For ``kind='editor'`` the path scope is part of the unique key —
    multiple editor tabs can coexist (one per file). For other system
    kinds there is at most one open tab per kind.
    """
    sm = get_sessionmaker()
    if kind not in _SYSTEM_KINDS:
        raise ValueError(f"ensure_system_tab: kind={kind!r} is not a system kind")
    content_ref = content_ref or {}
    path_key = (
        content_ref.get("path") if kind == "editor" else None
    )  # editor uniqueness scopes on path
    now = _utc_now_naive()
    async with sm() as db:
        stmt = (
            select(Tab)
            .where(
                Tab.session_id == sid,
                Tab.kind == kind,
                Tab.status == "open",
            )
            .order_by(Tab.created_at.desc())
        )
        candidates = (await db.execute(stmt)).scalars().all()
        match: Tab | None = None
        for c in candidates:
            if kind == "editor":
                if (c.content_ref or {}).get("path") == path_key:
                    match = c
                    break
            else:
                match = c
                break
        if match is not None:
            match.last_activity_at = now
            db.add(match)
            await db.commit()
            await db.refresh(match)
            return _serialize(match)
        # New row — append to end of strip.
        existing_positions = [
            p
            for p in (
                await db.execute(
                    select(Tab.position).where(
                        Tab.session_id == sid, Tab.status == "open"
                    )
                )
            )
            .scalars()
            .all()
            if p is not None
        ]
        position = (max(existing_positions) + 1) if existing_positions else 0
        tab = Tab(
            session_id=sid,
            kind=kind,
            title=title,
            position=position,
            pinned=False,
            status="open",
            content_ref=content_ref,
            created_at=now,
            updated_at=now,
            last_activity_at=now,
        )
        db.add(tab)
        await db.commit()
        await db.refresh(tab)
    payload = _serialize(tab)
    await _emit(sid, "tab.opened", payload)
    return payload
