"""Shared test fixtures.

Swap the process-wide async engine to an in-memory SQLite database so tests
run fast, hermetic, and without a live postgres. Clear the session-runtime
cache between tests so no state leaks across cases.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


# Force tests to use SQLite before polymath.config is imported.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LLM_MODEL", "openai:gpt-4o-mini")
os.environ.setdefault("OPENAI_API_KEY", "test-key-never-real")
os.environ.setdefault("ORQEST_WEB_PROVIDER", "none")
os.environ.setdefault("POLYMATH_MEMORY_DIR", "/tmp/polymath-test-memory")


@pytest_asyncio.fixture(autouse=True)
async def _isolated_db() -> AsyncIterator[None]:
    """Fresh in-memory SQLite engine + tables per test.

    Patches :mod:`polymath.db.session` globals so every route, endpoint,
    and runtime that asks for a session gets the ephemeral DB.
    """
    from polymath.db import session as session_module
    from polymath.db import models  # noqa: F401 — register tables

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, future=True
    )
    sm = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    prev_engine = session_module._engine
    prev_sm = session_module._sessionmaker
    session_module._engine = engine
    session_module._sessionmaker = sm

    yield

    session_module._engine = prev_engine
    session_module._sessionmaker = prev_sm
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clear_runtime_cache() -> AsyncIterator[None]:
    """Ensure the session-runtime cache is empty before each test."""
    from polymath import runtime

    runtime._runtimes.clear()
    yield
    runtime._runtimes.clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the FastAPI ASGI app."""
    from polymath.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def _frozen_config():
    """Reset the ``get_default_config`` lru_cache so env overrides land."""
    from polymath import config as config_module

    config_module.get_default_config.cache_clear()
    yield
    config_module.get_default_config.cache_clear()
