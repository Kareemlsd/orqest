"""SQLModel tables — Phase 0.

Schemas mirror the plan in ``mellow-twirling-bentley.md``. Alembic
migrations are intentionally skipped for the demo; bootstrap happens
via :func:`polymath.db.session.init_db`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    """Naive UTC timestamp.

    Postgres columns default to ``TIMESTAMP WITHOUT TIME ZONE``; asyncpg
    refuses tz-aware datetimes for those columns. We store naive UTC and
    treat every timestamp as UTC by convention. Switch to
    ``TIMESTAMP WITH TIME ZONE`` everywhere if we ever need proper offsets.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Session(SQLModel, table=True):
    """A chat session. One row per user conversation."""

    __tablename__ = "sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    title: str = Field(default="Untitled session")
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    # Pointer to the right-pane tab the user (or agent) most recently
    # activated. Persisted so reload returns to where the user was.
    # ``None`` when no tab has ever been focused.
    active_tab_id: UUID | None = Field(default=None, nullable=True)


class Message(SQLModel, table=True):
    """An AI-SDK-v6 style message preserved verbatim as JSON."""

    __tablename__ = "messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="sessions.id", index=True)
    role: str
    content_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utc_now)


class Plan(SQLModel, table=True):
    """Persisted snapshot of an :class:`orqest.ExecutionPlan`."""

    __tablename__ = "plans"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="sessions.id", index=True, unique=True)
    tasks_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=_utc_now)


class Artifact(SQLModel, table=True):
    """A file produced by the agent (figure, script, report, …)."""

    __tablename__ = "artifacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="sessions.id", index=True)
    kind: str
    mime: str
    label: str
    path: str
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=_utc_now)


class Tab(SQLModel, table=True):
    """A right-pane tab in the unified dynamic panel.

    The right pane is no longer a fixed strip of tabs hard-coded in
    ``ComputerPane.tsx``; it's driven by this manifest. Tabs are typed
    via ``kind`` (``shell`` / ``files`` / ``browser`` / ``editor`` /
    ``chart_gallery`` / ``report`` / ``memory`` / ``agents`` for system
    surfaces, ``component`` for agent-emitted :class:`UIComponentSpec`
    containers). The frontend routes each row to the matching renderer.

    Cognitive surfaces ship as two additional system kinds — ``memory``
    (the three-section semantic/episodic/procedural browser) and
    ``agents`` (the live sub-agent roster). They auto-spawn on the first
    relevant event in their family (see :mod:`polymath.tab_respawn`).

    Closure is soft so closed tabs can be restored within a 24-hour
    window — the row stays with ``status='closed'`` and ``closed_at`` set;
    a periodic GC may drop tombstones older than the window. Reordering
    is via ``position`` (lower comes first); auto-respawn keys on
    ``(session_id, kind, content_ref->>'path')`` for the editor and on
    ``(session_id, kind)`` for the other system kinds so closing a tab
    and re-firing the same event re-creates it cleanly.
    """

    __tablename__ = "tabs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="sessions.id", index=True)
    kind: str
    title: str
    position: int = 0
    pinned: bool = False
    status: str = Field(default="open")
    content_ref: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    last_activity_at: datetime = Field(default_factory=_utc_now)
    closed_at: datetime | None = Field(default=None, nullable=True)
