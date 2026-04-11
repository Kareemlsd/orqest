"""SQLite-backed local memory store.

Uses aiosqlite for async access. Creates the table lazily on first use.
Full-text search via FTS5 when available, with LIKE fallback.
Memory operations are best-effort: errors are logged, never raised to the caller.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from orqest.memory.store import MemoryEntry, MemoryFilter

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'semantic',
    source_agent TEXT NOT NULL DEFAULT 'unknown',
    confidence REAL NOT NULL DEFAULT 1.0,
    embedding TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    last_accessed TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    reliability_score REAL NOT NULL DEFAULT 1.0
);
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(id, content, content=memories, content_rowid=rowid);
"""

_FTS_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(id, content)
    VALUES (new.id, new.content);
END;
"""

_FTS_TRIGGER_DELETE = """
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, id, content)
    VALUES('delete', old.id, old.content);
END;
"""

_FTS_TRIGGER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, id, content)
    VALUES('delete', old.id, old.content);
    INSERT INTO memories_fts(id, content)
    VALUES (new.id, new.content);
END;
"""


class LocalMemoryStore:
    """SQLite-backed memory store with optional FTS5 full-text search."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize with the path to the SQLite database file."""
        self._db_path = Path(db_path).expanduser()
        self._db: aiosqlite.Connection | None = None
        self._fts_available: bool = False

    async def _ensure_db(self) -> aiosqlite.Connection:
        """Lazily open the database and create tables on first access."""
        if self._db is not None:
            return self._db

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()

        # Attempt FTS5 setup — gracefully degrade if unavailable
        try:
            fts_sql = _CREATE_FTS + _FTS_TRIGGER_INSERT
            fts_sql += _FTS_TRIGGER_DELETE + _FTS_TRIGGER_UPDATE
            await self._db.executescript(fts_sql)
            await self._db.commit()
            self._fts_available = True
        except Exception:
            logger.debug("FTS5 not available, falling back to LIKE queries")
            self._fts_available = False

        return self._db

    async def store(self, entry: MemoryEntry) -> str:
        """Persist a memory entry. Returns the entry id."""
        try:
            db = await self._ensure_db()
            await db.execute(
                """INSERT OR REPLACE INTO memories
                   (id, content, memory_type, source_agent, confidence,
                    embedding, metadata, created_at, last_accessed,
                    access_count, reliability_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.content,
                    entry.memory_type,
                    entry.source_agent,
                    entry.confidence,
                    json.dumps(entry.embedding) if entry.embedding else None,
                    json.dumps(entry.metadata),
                    entry.created_at.isoformat(),
                    entry.last_accessed.isoformat(),
                    entry.access_count,
                    entry.reliability_score,
                ),
            )
            await db.commit()
        except Exception:
            logger.warning("Failed to store memory entry {id}", id=entry.id)
        return entry.id

    async def recall(
        self,
        query: str,
        *,
        k: int = 5,
        filters: MemoryFilter | None = None,
    ) -> list[MemoryEntry]:
        """Retrieve entries matching the query, applying optional filters."""
        try:
            db = await self._ensure_db()
            conditions: list[str] = []
            params: list[Any] = []

            if self._fts_available:
                conditions.append(
                    "m.id IN (SELECT id FROM memories_fts WHERE content MATCH ?)"
                )
                params.append(f'"{query}"')
            else:
                conditions.append("m.content LIKE ?")
                params.append(f"%{query}%")

            if filters:
                if filters.memory_type is not None:
                    conditions.append("m.memory_type = ?")
                    params.append(filters.memory_type)
                if filters.source_agent is not None:
                    conditions.append("m.source_agent = ?")
                    params.append(filters.source_agent)
                if filters.min_confidence is not None:
                    conditions.append("m.confidence >= ?")
                    params.append(filters.min_confidence)
                if filters.min_reliability is not None:
                    conditions.append("m.reliability_score >= ?")
                    params.append(filters.min_reliability)

            where = " AND ".join(conditions) if conditions else "1=1"
            # The WHERE clause is built from static column names, not user input
            sql = f"""
                SELECT * FROM memories m
                WHERE {where}
                ORDER BY m.last_accessed DESC
                LIMIT ?
            """  # noqa: S608
            params.append(k)

            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()

            entries: list[MemoryEntry] = []
            now = datetime.now()
            for row in rows:
                entry = _row_to_entry(row)
                entries.append(entry)
                # Update access metadata
                await db.execute(
                    """UPDATE memories
                       SET last_accessed = ?, access_count = access_count + 1
                       WHERE id = ?""",
                    (now.isoformat(), entry.id),
                )
            await db.commit()
        except Exception as exc:
            logger.warning(
                "Failed to recall memories for query {q!r}: {e}",
                q=query,
                e=exc,
            )
            return []
        else:
            return entries

    async def forget(self, entry_id: str) -> None:
        """Remove a memory entry by id. No error if not found."""
        try:
            db = await self._ensure_db()
            await db.execute("DELETE FROM memories WHERE id = ?", (entry_id,))
            await db.commit()
        except Exception:
            logger.warning("Failed to forget memory {id}", id=entry_id)

    async def update_reliability(
        self, entry_id: str, *, success: bool
    ) -> None:
        """Adjust reliability score. On failure, multiply by 0.7. Prune if below 0.1."""
        if success:
            return

        try:
            db = await self._ensure_db()
            await db.execute(
                """UPDATE memories
                   SET reliability_score = reliability_score * 0.7
                   WHERE id = ?""",
                (entry_id,),
            )
            # Prune entries that have become unreliable
            await db.execute(
                "DELETE FROM memories WHERE id = ? AND reliability_score < 0.1",
                (entry_id,),
            )
            await db.commit()
        except Exception:
            logger.warning(
                "Failed to update reliability for {id}", id=entry_id
            )

    async def count(self) -> int:
        """Return the total number of stored entries."""
        try:
            db = await self._ensure_db()
            cursor = await db.execute("SELECT COUNT(*) FROM memories")
            row = await cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            logger.warning("Failed to count memories")
            return 0

    async def close(self) -> None:
        """Close the underlying aiosqlite connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None


def _row_to_entry(row: aiosqlite.Row) -> MemoryEntry:
    """Convert a database row to a MemoryEntry."""
    embedding_raw = row["embedding"]
    return MemoryEntry(
        id=row["id"],
        content=row["content"],
        memory_type=row["memory_type"],
        source_agent=row["source_agent"],
        confidence=row["confidence"],
        embedding=json.loads(embedding_raw) if embedding_raw else None,
        metadata=json.loads(row["metadata"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_accessed=datetime.fromisoformat(row["last_accessed"]),
        access_count=row["access_count"],
        reliability_score=row["reliability_score"],
    )
