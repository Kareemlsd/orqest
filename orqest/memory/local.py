"""SQLite-backed local memory store.

Uses aiosqlite for async access. Creates the table lazily on first use.
Full-text search via FTS5 when available, with LIKE fallback.

Recall dispatches to a :class:`RetrievalStrategy` keyed by
``filters.memory_type`` — semantic / episodic / procedural — so each
cognitive memory kind has its own retrieval algorithm without giant
if/else branches in the store.

Memory operations are best-effort: errors are logged, never raised to the caller.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from orqest.memory.config import MemoryConfig, PerKindConfig
from orqest.memory.store import MemoryEntry, MemoryFilter
from orqest.memory.strategies import (
    RetrievalStrategy,
    default_strategy_table,
)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    structured_content TEXT,
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
    """SQLite-backed memory store with optional FTS5 full-text search.

    Per-kind retrieval strategies are configurable via the ``strategies``
    constructor argument; the default table provides Semantic / Episodic
    / Procedural strategies. Override individual entries to inject
    custom behavior (e.g. a fuzzy judge for procedural recall).
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        config: MemoryConfig | None = None,
        strategies: dict[str, RetrievalStrategy] | None = None,
    ) -> None:
        """Initialize the store.

        Args:
            db_path: SQLite file path (created lazily). When omitted,
                ``config.local_db_path`` is used.
            config: Memory subsystem configuration. Supplies the per-kind
                reliability policy (``decay_on_failure`` / ``prune_below``)
                read by :meth:`update_reliability`. Defaults to
                :class:`MemoryConfig` defaults.
            strategies: Optional override of the per-kind retrieval table.
                Defaults to ``default_strategy_table()`` (Semantic / Episodic
                / Procedural). Unknown ``memory_type`` values fall back to
                the ``"semantic"`` strategy at recall time.
        """
        self._config = config or MemoryConfig()
        resolved_path = (
            db_path if db_path is not None else self._config.local_db_path
        )
        self._db_path = Path(resolved_path).expanduser()
        self._db: aiosqlite.Connection | None = None
        self._fts_available: bool = False
        self._strategies = strategies or default_strategy_table()

    def _policy_for(self, memory_type: str) -> PerKindConfig:
        """Per-kind reliability policy; unknown kinds fall back to semantic."""
        return getattr(self._config, memory_type, self._config.semantic)

    async def _ensure_db(self) -> aiosqlite.Connection:
        """Lazily open the database and create tables on first access.

        Performs a best-effort ``ALTER TABLE`` to add the
        ``structured_content`` column to pre-existing databases that
        were created before procedural memory shipped.
        """
        if self._db is not None:
            return self._db

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_TABLE)
        # Best-effort migration for older DBs missing structured_content.
        try:
            await self._db.execute(
                "ALTER TABLE memories ADD COLUMN structured_content TEXT"
            )
        except Exception:
            # Column already exists or table was just created with it.
            pass
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
                   (id, content, structured_content, memory_type, source_agent,
                    confidence, embedding, metadata, created_at, last_accessed,
                    access_count, reliability_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.content,
                    json.dumps(entry.structured_content)
                    if entry.structured_content is not None
                    else None,
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
        """Retrieve entries matching the query, applying optional filters.

        Dispatches to the strategy keyed by ``filters.memory_type``.
        Unknown / missing memory_type → ``"semantic"`` strategy
        (preserves v0.0.1 behavior).
        """
        try:
            db = await self._ensure_db()
            kind = (filters.memory_type if filters else None) or "semantic"
            strategy = self._strategies.get(kind, self._strategies.get("semantic"))
            if strategy is None:
                return []

            rows = await strategy.recall(
                db,
                query,
                k=k,
                filters=filters,
                fts_available=self._fts_available,
            )

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
        """Decay an entry's reliability on a failed-recall report.

        ``success`` is a no-op — reliability only decays. On failure the
        entry's reliability is multiplied by the per-kind
        ``decay_on_failure`` factor, and the entry is pruned if it drops
        below the per-kind ``prune_below`` floor (see :class:`PerKindConfig`).
        """
        if success:
            return

        try:
            db = await self._ensure_db()
            cursor = await db.execute(
                "SELECT memory_type FROM memories WHERE id = ?", (entry_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return
            policy = self._policy_for(row["memory_type"])
            await db.execute(
                "UPDATE memories SET reliability_score = reliability_score * ? "
                "WHERE id = ?",
                (policy.decay_on_failure, entry_id),
            )
            # Prune entries that have decayed below the reliability floor.
            await db.execute(
                "DELETE FROM memories WHERE id = ? AND reliability_score < ?",
                (entry_id, policy.prune_below),
            )
            await db.commit()
        except Exception:
            logger.warning(
                "Failed to update reliability for {id}", id=entry_id
            )

    async def prune_expired(self) -> int:
        """Delete entries older than their per-kind ``ttl_days``.

        Best-effort maintenance: a kind whose :class:`PerKindConfig.ttl_days`
        is ``None`` is never pruned. Errors are logged, never raised — the
        method returns the number of rows deleted (``0`` on failure).
        """
        pruned = 0
        try:
            db = await self._ensure_db()
            now = datetime.now()
            for kind in ("semantic", "episodic", "procedural"):
                ttl_days = getattr(self._config, kind).ttl_days
                if ttl_days is None:
                    continue
                cutoff = (now - timedelta(days=ttl_days)).isoformat()
                cursor = await db.execute(
                    "DELETE FROM memories "
                    "WHERE memory_type = ? AND created_at < ?",
                    (kind, cutoff),
                )
                pruned += max(0, cursor.rowcount)
            await db.commit()
        except Exception:
            logger.warning("prune_expired failed")
        return pruned

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

    async def list_recent(
        self,
        *,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        """Return the most recently stored entries, newest first.

        Browse-style enumeration that complements :meth:`recall` (which
        is query-driven). Used by consumer surfaces that want to render
        a "memory inspector" view without issuing a search. Filters
        by ``memory_type`` when supplied; ``None`` returns every kind.

        Best-effort like the other read paths — returns ``[]`` on any
        SQLite failure rather than raising.
        """
        try:
            db = await self._ensure_db()
            sql = "SELECT * FROM memories"
            params: tuple[Any, ...] = ()
            if memory_type:
                sql += " WHERE memory_type = ?"
                params = (memory_type,)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params = (*params, max(1, min(int(limit), 500)))
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()
            return [_row_to_entry(row) for row in rows]
        except Exception:
            logger.warning(
                "list_recent failed (memory_type={mt!r})", mt=memory_type
            )
            return []

    async def close(self) -> None:
        """Close the underlying aiosqlite connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None


def _row_to_entry(row: aiosqlite.Row) -> MemoryEntry:
    """Convert a database row to a MemoryEntry."""
    embedding_raw = row["embedding"]
    structured_raw: Any = None
    # New column may not be present in some legacy rows / mocks; tolerate.
    try:
        structured_raw = row["structured_content"]
    except (IndexError, KeyError):
        structured_raw = None
    return MemoryEntry(
        id=row["id"],
        content=row["content"],
        structured_content=json.loads(structured_raw) if structured_raw else None,
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
