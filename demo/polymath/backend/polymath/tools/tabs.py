"""Agent-facing tools for the right-pane manifest.

Three pydantic-ai ``Tool``s let the agent drive the dynamic tab strip
directly:

* :func:`open_tab` — open a fresh tab and return its id. The agent picks
  ``kind`` (``component`` for arbitrary content; system kinds for
  re-opening Shell/Files/Browser when the user has closed them) and a
  human-readable ``title``. ``content_ref`` is a freeform JSON blob the
  matching renderer interprets — for ``kind='component'`` it's typically
  ``{"component_ids": [...]}`` linking to previously-emitted
  :class:`UIComponentSpec`s.
* :func:`update_tab` — patch fields on an existing tab. Most useful with
  ``focus=true`` to draw the user's eye when presenting a final result.
* :func:`close_tab` — soft-close a tab the agent considers no longer
  relevant. The user can still restore within 24 h.

The tools call the existing service helpers in
:mod:`polymath.routers.tabs` (``_emit``, ``_serialize``, the DB session
factory) so the bus events the frontend already subscribes to flow the
same way they do when the user clicks a button — there is no separate
"agent path" the frontend needs to learn about.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool
from sqlmodel import select

from polymath.db.models import Session, Tab
from polymath.db.session import get_sessionmaker
from polymath.routers.tabs import _emit, _serialize, _utc_now_naive
from polymath.state import PolymathState


_VALID_KINDS = (
    "component",
    "shell",
    "files",
    "browser",
    "editor",
    "chart_gallery",
    "report",
)


# ---- open_tab ---------------------------------------------------------


async def _open_tab(
    ctx: RunContext[PolymathState],
    kind: Annotated[
        str,
        "Tab kind: 'component' for arbitrary agent content, or one of the "
        "system kinds 'shell' / 'files' / 'browser' / 'editor' / "
        "'chart_gallery' / 'report' to re-open a system surface.",
    ],
    title: Annotated[
        str,
        "Human-readable tab title shown in the strip. Keep it short — the "
        "tab cell caps at ~200 px wide.",
    ],
    content_ref: Annotated[
        dict[str, Any] | None,
        "Free-form JSON the matching renderer interprets. For "
        "kind='component', use {'component_ids': [...]} to bind one or "
        "more UIComponentSpecs to this tab. Optional.",
    ] = None,
    pinned: Annotated[
        bool,
        "Pin the tab so it stays visible even after the user closes "
        "siblings. Default false.",
    ] = False,
) -> str:
    """Open a new right-pane tab and return its id."""
    sid_str = ctx.deps.session_id
    try:
        sid = UUID(sid_str)
    except (ValueError, TypeError) as exc:
        return json.dumps({"error": f"invalid session id: {exc}"})
    if kind not in _VALID_KINDS:
        return json.dumps(
            {"error": f"unknown kind: {kind!r}. Valid: {list(_VALID_KINDS)}"}
        )

    sm = get_sessionmaker()
    now = _utc_now_naive()
    async with sm() as db:
        # Append to end of strip.
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
            id=uuid4(),
            session_id=sid,
            kind=kind,
            title=title,
            position=position,
            pinned=pinned,
            status="open",
            content_ref=content_ref or {},
            created_at=now,
            updated_at=now,
            last_activity_at=now,
        )
        db.add(tab)
        await db.commit()
        await db.refresh(tab)
    payload = _serialize(tab)
    await _emit(sid, "tab.opened", payload)
    return json.dumps({"tab_id": str(tab.id), "kind": tab.kind, "title": tab.title})


# ---- update_tab -------------------------------------------------------


async def _update_tab(
    ctx: RunContext[PolymathState],
    tab_id: Annotated[str, "ID returned by open_tab."],
    title: Annotated[str | None, "Rename. Optional."] = None,
    pinned: Annotated[bool | None, "Pin / unpin. Optional."] = None,
    focus: Annotated[
        bool,
        "When true, set this tab as the session's active tab so the user "
        "sees it. Subject to the user's 5 s click lockout. Default false.",
    ] = False,
    content_ref: Annotated[
        dict[str, Any] | None,
        "Replace content_ref wholesale. Use this to add new component "
        "ids to a kind='component' tab's binding list. Optional.",
    ] = None,
) -> str:
    """Patch a tab's fields. Returns the updated row's JSON."""
    sid_str = ctx.deps.session_id
    try:
        sid = UUID(sid_str)
        tid = UUID(tab_id)
    except (ValueError, TypeError) as exc:
        return json.dumps({"error": f"invalid id: {exc}"})

    sm = get_sessionmaker()
    now = _utc_now_naive()
    async with sm() as db:
        tab = await db.get(Tab, tid)
        if tab is None or tab.session_id != sid:
            return json.dumps({"error": f"tab not found: {tab_id}"})
        changed = False
        if title is not None and title != tab.title:
            tab.title = title
            changed = True
        if pinned is not None and pinned != tab.pinned:
            tab.pinned = pinned
            changed = True
        if content_ref is not None:
            tab.content_ref = content_ref
            changed = True
        if changed:
            tab.updated_at = now
            tab.last_activity_at = now
            db.add(tab)
            await db.commit()
            await db.refresh(tab)
        # Focus is a separate column on the Session table; do it after
        # the tab row commit so a focus-only update still emits the
        # right event sequence (updated → focused).
        focused_payload: dict[str, Any] | None = None
        if focus and tab.status == "open":
            sess = await db.get(Session, sid)
            if sess is not None:
                sess.active_tab_id = tab.id
                tab.last_activity_at = now
                db.add(sess)
                db.add(tab)
                await db.commit()
                await db.refresh(tab)
                focused_payload = _serialize(tab)
    if changed:
        await _emit(sid, "tab.updated", _serialize(tab))
    if focused_payload is not None:
        await _emit(sid, "tab.focused", focused_payload)
    return json.dumps(
        {"ok": True, "tab_id": str(tab.id), "focus": focus and tab.status == "open"}
    )


# ---- close_tab --------------------------------------------------------


async def _close_tab(
    ctx: RunContext[PolymathState],
    tab_id: Annotated[str, "ID returned by open_tab."],
) -> str:
    """Soft-close a tab. The user can still restore within 24 hours."""
    sid_str = ctx.deps.session_id
    try:
        sid = UUID(sid_str)
        tid = UUID(tab_id)
    except (ValueError, TypeError) as exc:
        return json.dumps({"error": f"invalid id: {exc}"})

    sm = get_sessionmaker()
    now = _utc_now_naive()
    async with sm() as db:
        tab = await db.get(Tab, tid)
        if tab is None or tab.session_id != sid:
            return json.dumps({"error": f"tab not found: {tab_id}"})
        if tab.status != "closed":
            tab.status = "closed"
            tab.closed_at = now
            tab.updated_at = now
            db.add(tab)
        sess = await db.get(Session, sid)
        if sess is not None and sess.active_tab_id == tab.id:
            sess.active_tab_id = None
            db.add(sess)
        await db.commit()
        await db.refresh(tab)
    await _emit(sid, "tab.closed", _serialize(tab))
    return json.dumps({"ok": True, "tab_id": str(tab.id)})


# ---- pydantic-ai Tool wrappers ----------------------------------------


open_tab = Tool(_open_tab, name="open_tab")
update_tab = Tool(_update_tab, name="update_tab")
close_tab = Tool(_close_tab, name="close_tab")
