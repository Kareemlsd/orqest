"""SQLite-backed tool persistence — runs INSIDE the container.

Stores runtime-promoted tools per user. The database file is at
``/data/orqest-tools.sqlite`` (mounted as a Docker named volume
``orqest-user-<user_id>``). The file survives container teardown; user A's
volume never crosses to user B.

Schema:

.. code-block:: sql

    CREATE TABLE IF NOT EXISTS tools (
        name TEXT NOT NULL,
        version INTEGER NOT NULL,
        description TEXT NOT NULL,
        parameters TEXT NOT NULL,           -- JSON Schema
        implementation TEXT NOT NULL,
        implementation_hash TEXT NOT NULL,  -- SHA-256 of implementation
        allowed_imports TEXT NOT NULL,      -- JSON array
        dependencies TEXT NOT NULL,         -- JSON array of pip specifiers
        promoted_at TEXT NOT NULL,
        promoted_from_agent TEXT,
        invocation_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (name, version)
    );

API:

* :meth:`ToolStore.replay` — load all latest-version tools at startup.
* :meth:`ToolStore.persist` — INSERT a tool; if name already exists with
  same hash, no-op (deduplication); if name exists with different hash,
  bump version (auditable history).
* :meth:`ToolStore.forget` — remove by ``(name, version)``.
* :meth:`ToolStore.record_invocation` — increment counter.

Uses ``sqlite3`` (stdlib, blocking) deliberately — the runtime container
runs sync code at the SQLite boundary and async code at the FastMCP
boundary; mixing async sqlite (aiosqlite) here would buy nothing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tools (
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    description TEXT NOT NULL,
    parameters TEXT NOT NULL,
    implementation TEXT NOT NULL,
    implementation_hash TEXT NOT NULL,
    allowed_imports TEXT NOT NULL,
    dependencies TEXT NOT NULL,
    promoted_at TEXT NOT NULL,
    promoted_from_agent TEXT,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (name, version)
);
CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name);
"""


@dataclass(frozen=True)
class PersistedTool:
    """Snapshot of a persisted tool — what :meth:`ToolStore.replay` returns."""

    name: str
    version: int
    description: str
    parameters: dict[str, Any]
    implementation: str
    implementation_hash: str
    allowed_imports: list[str]
    dependencies: list[str]
    promoted_at: str
    promoted_from_agent: str | None
    invocation_count: int


def _hash_impl(implementation: str) -> str:
    """Stable content hash for deduplication."""
    return hashlib.sha256(implementation.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ToolStore:
    """SQLite-backed runtime tool persistence."""

    def __init__(self, db_path: str | Path = "/data/orqest-tools.sqlite") -> None:
        """Open / create the database.

        Args:
            db_path: SQLite file path. Default ``/data/orqest-tools.sqlite``
                matches the Docker volume mount inside the runtime image.
                Use ``":memory:"`` for tests.

        """
        # ``check_same_thread=False`` because FastMCP serves on multiple
        # threads (worker pool for sync tools); we serialize writes via
        # connection-level locking.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def replay(self) -> list[PersistedTool]:
        """Return all latest-version tools (one entry per name).

        On collision (multiple versions of same name), the highest version
        wins — this is the canonical "current" definition. Older versions
        remain in the DB for audit but aren't replayed into the registry.
        """
        cursor = self._conn.execute(
            """
            SELECT t.* FROM tools t
            INNER JOIN (
                SELECT name, MAX(version) AS max_v
                FROM tools GROUP BY name
            ) latest ON t.name = latest.name AND t.version = latest.max_v
            ORDER BY t.name
            """
        )
        return [self._row_to_tool(row) for row in cursor.fetchall()]

    def get(self, name: str, version: int | None = None) -> PersistedTool | None:
        """Get a specific tool. ``version=None`` → latest."""
        if version is None:
            cursor = self._conn.execute(
                """
                SELECT * FROM tools
                WHERE name = ?
                ORDER BY version DESC LIMIT 1
                """,
                (name,),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM tools WHERE name = ? AND version = ?",
                (name, version),
            )
        row = cursor.fetchone()
        return self._row_to_tool(row) if row else None

    def persist(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        implementation: str,
        allowed_imports: list[str],
        dependencies: list[str] | None = None,
        promoted_from_agent: str | None = None,
    ) -> PersistedTool:
        """Persist a tool.

        Behaviour:

        * If ``name`` doesn't exist → INSERT with version=1.
        * If ``name`` exists with same ``implementation_hash`` → no-op
          (return the existing latest version).
        * If ``name`` exists with different ``implementation_hash`` →
          INSERT with version=max+1 (auditable history; older versions
          remain queryable).
        """
        impl_hash = _hash_impl(implementation)

        # Check existing
        existing = self.get(name)
        if existing is not None and existing.implementation_hash == impl_hash:
            return existing

        new_version = (existing.version + 1) if existing else 1
        self._conn.execute(
            """
            INSERT INTO tools
                (name, version, description, parameters, implementation,
                 implementation_hash, allowed_imports, dependencies,
                 promoted_at, promoted_from_agent, invocation_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                name,
                new_version,
                description,
                json.dumps(parameters),
                implementation,
                impl_hash,
                json.dumps(list(allowed_imports)),
                json.dumps(list(dependencies) if dependencies else []),
                _now_iso(),
                promoted_from_agent,
            ),
        )
        self._conn.commit()
        result = self.get(name, version=new_version)
        assert result is not None  # just inserted
        return result

    def forget(self, name: str, version: int | None = None) -> int:
        """Remove tool(s). ``version=None`` → all versions of that name.

        Returns the number of rows deleted.
        """
        if version is None:
            cursor = self._conn.execute(
                "DELETE FROM tools WHERE name = ?", (name,)
            )
        else:
            cursor = self._conn.execute(
                "DELETE FROM tools WHERE name = ? AND version = ?",
                (name, version),
            )
        self._conn.commit()
        return cursor.rowcount or 0

    def record_invocation(self, name: str, version: int | None = None) -> None:
        """Increment invocation_count for a tool. Best-effort (silent on miss)."""
        if version is None:
            tool = self.get(name)
            if tool is None:
                return
            version = tool.version
        self._conn.execute(
            "UPDATE tools SET invocation_count = invocation_count + 1 "
            "WHERE name = ? AND version = ?",
            (name, version),
        )
        self._conn.commit()

    def list_all(self) -> list[PersistedTool]:
        """Every row, ordered by (name, version DESC). For audit/debug only."""
        cursor = self._conn.execute(
            "SELECT * FROM tools ORDER BY name, version DESC"
        )
        return [self._row_to_tool(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_tool(row: sqlite3.Row) -> PersistedTool:
        return PersistedTool(
            name=row["name"],
            version=row["version"],
            description=row["description"],
            parameters=json.loads(row["parameters"]),
            implementation=row["implementation"],
            implementation_hash=row["implementation_hash"],
            allowed_imports=json.loads(row["allowed_imports"]),
            dependencies=json.loads(row["dependencies"]),
            promoted_at=row["promoted_at"],
            promoted_from_agent=row["promoted_from_agent"],
            invocation_count=row["invocation_count"],
        )


__all__ = [
    "PersistedTool",
    "ToolStore",
]
