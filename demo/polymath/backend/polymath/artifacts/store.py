"""Artifact persistence — DB rows + sandbox-file streaming.

An Artifact is anything the agent produced for the user: a chart PNG,
a markdown report, a generated PDF, a script, a dataset. The file itself
lives inside the session's sandbox at ``path`` (relative to ``/workspace``);
this module records the metadata + emits ``artifact.created`` on the bus.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlmodel import select

from polymath.db.models import Artifact
from polymath.db.session import get_sessionmaker
from polymath.runtime import emit


async def create_artifact(
    *,
    session_id: UUID | str,
    kind: str,
    mime: str,
    label: str,
    path: str,
    size_bytes: int = 0,
) -> Artifact:
    """Insert an Artifact row and emit an ``artifact.created`` event."""
    sm = get_sessionmaker()
    row = Artifact(
        id=uuid4(),
        session_id=UUID(str(session_id)),
        kind=kind,
        mime=mime,
        label=label,
        path=path,
        size_bytes=size_bytes,
    )
    async with sm() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    await emit(
        str(session_id),
        "artifact.created",
        {
            "id": str(row.id),
            "kind": kind,
            "mime": mime,
            "label": label,
            "path": path,
            "size": size_bytes,
        },
    )
    return row


async def list_artifacts(session_id: UUID | str) -> list[Artifact]:
    """Return artifacts for *session_id*, newest first."""
    sm = get_sessionmaker()
    async with sm() as db:
        result = await db.execute(
            select(Artifact)
            .where(Artifact.session_id == UUID(str(session_id)))
            .order_by(Artifact.created_at.desc())
        )
        return list(result.scalars().all())


async def get_artifact(artifact_id: UUID | str) -> Artifact | None:
    sm = get_sessionmaker()
    async with sm() as db:
        return await db.get(Artifact, UUID(str(artifact_id)))
