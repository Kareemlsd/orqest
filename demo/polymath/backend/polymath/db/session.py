"""Async SQLAlchemy engine + session maker + init helper.

Uses :func:`SQLModel.metadata.create_all` for the demo — Phase 0 does
not ship alembic migrations. :func:`init_db` retries with exponential
backoff so the backend can come up before postgres finishes booting.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from polymath.config import get_default_config

# Import models for side effect (registers them on SQLModel.metadata).
from polymath.db import models  # noqa: F401

logger = logging.getLogger(__name__)


def _build_engine():
    cfg = get_default_config()
    # psycopg3 async driver
    url = cfg.DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_async_engine(url, echo=False, future=True)


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    """Return the process-wide async engine, building it on first call."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = _build_engine()
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the async session maker."""
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def init_db(*, max_wait_s: float = 30.0, initial_delay_s: float = 0.5) -> None:
    """Create tables, retrying until postgres is reachable.

    Implements exponential backoff capped at ``max_wait_s`` total wait.

    After ``create_all`` runs the additive migration helper applies any
    column additions that ``create_all`` won't perform on its own. We
    skip Alembic for the demo (see :file:`db/models.py`) so this is the
    minimum-viable migration surface — every entry is idempotent and
    safe to re-run on every boot.
    """
    engine = get_engine()
    deadline_s = max_wait_s
    delay = initial_delay_s
    elapsed = 0.0

    while True:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
                await _apply_additive_migrations(conn)
            logger.info("polymath: database initialized")
            return
        except Exception as exc:  # noqa: BLE001
            if elapsed >= deadline_s:
                logger.error("polymath: init_db giving up after %.1fs: %s", elapsed, exc)
                raise
            logger.warning("polymath: init_db retry in %.1fs (%s)", delay, exc)
            await asyncio.sleep(delay)
            elapsed += delay
            delay = min(delay * 2, 5.0)


async def _apply_additive_migrations(conn) -> None:
    """Apply hand-written column additions ``create_all`` won't do.

    Each statement uses ``IF NOT EXISTS`` (postgres ≥ 9.6) so re-running
    is a no-op. SQLite tolerates the same syntax for most ALTER variants
    via the ``ALTER TABLE ... ADD COLUMN`` form, but we wrap the
    statements in a try/except to keep the demo DB choice flexible: any
    failure here is logged and swallowed because the affected feature
    degrades gracefully (the unified-tab right pane simply won't have an
    `active_tab_id` pointer until the column is added by hand).
    """
    from sqlalchemy import text

    statements: tuple[str, ...] = (
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS active_tab_id UUID NULL",
    )
    for stmt in statements:
        try:
            await conn.execute(text(stmt))
        except Exception as exc:  # noqa: BLE001
            logger.warning("polymath: additive migration skipped (%s): %s", stmt, exc)
