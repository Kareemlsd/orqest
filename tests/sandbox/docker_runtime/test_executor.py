"""Tests for orqest.sandbox.docker_runtime.executor.

These tests run against the host's real ``uv`` + a tempdir workspace
(no Docker daemon needed). They exercise the full per-agent venv +
subprocess execution path.

Skip-if-no-uv: tests check for ``uv`` on PATH and skip cleanly when
unavailable.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from orqest.sandbox.docker_runtime.executor import (
    Executor,
    ExecutorConfig,
    _pkg_name,
)

_uv_available = shutil.which("uv") is not None
_skip_if_no_uv = pytest.mark.skipif(
    not _uv_available, reason="uv binary not on PATH; skipping executor venv tests"
)


# --- _pkg_name -------------------------------------------------------------


class TestPkgName:
    def test_bare_name(self):
        assert _pkg_name("pandas") == "pandas"

    def test_version_specifier(self):
        assert _pkg_name("pandas>=2.0") == "pandas"
        assert _pkg_name("numpy<2") == "numpy"
        assert _pkg_name("httpx==0.27.0") == "httpx"
        assert _pkg_name("requests~=2.31") == "requests"

    def test_extras_normalized(self):
        """pandas[extras]>=2.0 should normalize to pandas (extras stripped)."""
        assert _pkg_name("pandas[extras]>=2.0") == "pandas"
        assert _pkg_name("uvicorn[standard]") == "uvicorn"

    def test_whitespace_stripped(self):
        assert _pkg_name(" pandas ") == "pandas"


# --- Executor lifecycle (real uv) ------------------------------------------


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def executor(workspace):
    return Executor(ExecutorConfig(
        workspace_root=workspace,
        session_id="test-session",
        allowed_packages=frozenset(),
    ))


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_ensure_venv_creates_directory(executor):
    await executor.ensure_venv("alice")
    assert executor.agent_python("alice").exists()


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_ensure_venv_idempotent(executor):
    """Calling twice doesn't recreate the venv (no error, no drama)."""
    await executor.ensure_venv("alice")
    mtime1 = executor.agent_python("alice").stat().st_mtime
    await executor.ensure_venv("alice")
    mtime2 = executor.agent_python("alice").stat().st_mtime
    assert mtime1 == mtime2  # not recreated


# --- execute (safe path) ---------------------------------------------------


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_execute_safe_arithmetic(executor):
    result = await executor.execute(
        code="return args['x'] + args['y']",
        args={"x": 3, "y": 4},
        allowed_imports=set(),
        agent_id="alice",
        timeout_s=10.0,
    )
    assert result.success is True
    assert result.output == 7


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_execute_captures_user_exception(executor):
    result = await executor.execute(
        code="raise ValueError('boom')",
        args={},
        allowed_imports=set(),
        agent_id="alice",
        timeout_s=5.0,
    )
    assert result.success is False
    assert "ValueError" in result.error
    assert "boom" in result.error


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_execute_timeout(executor):
    result = await executor.execute(
        code="while True: pass",
        args={},
        allowed_imports=set(),
        agent_id="alice",
        timeout_s=1.0,
    )
    assert result.success is False
    assert "timed out" in result.error


# --- Static validation ----------------------------------------------------


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_execute_validates_imports(executor):
    """Disallowed import is rejected at validate stage (before subprocess)."""
    result = await executor.execute(
        code="import os; return os.getcwd()",
        args={},
        allowed_imports=set(),  # empty → rejects any import
        agent_id="alice",
        timeout_s=5.0,
    )
    assert result.success is False
    assert "validation failed" in result.error


# --- Dependency installation ----------------------------------------------


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_dep_rejected_when_not_in_allowlist(executor):
    """Default-deny: empty allowed_packages rejects all declared deps."""
    result = await executor.execute(
        code="return 1",
        args={},
        allowed_imports={"pandas"},
        agent_id="alice",
        dependencies=["pandas"],
        timeout_s=10.0,
    )
    assert result.success is False
    assert "not in allowed_packages" in result.error
    assert "pandas" in result.error


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_dep_normalized_for_allowlist_check(workspace):
    """pandas[extras]>=2.0 should match a 'pandas' allowlist entry."""
    executor = Executor(ExecutorConfig(
        workspace_root=workspace,
        session_id="test-session",
        allowed_packages=frozenset({"pandas"}),  # bare name
    ))
    # We can verify the install attempt happens (and fails with a real pip
    # error or succeeds — both prove the allowlist check passed).
    # Just check the rejection message does NOT appear.
    result = await executor.execute(
        code="return 1",
        args={},
        allowed_imports={"pandas"},
        agent_id="alice",
        dependencies=["pandas[extras]>=2.0"],  # extras stripped → 'pandas' matches
        timeout_s=60.0,  # generous; real install takes ~5-15s
    )
    # Either install worked → success=True OR install failed (network etc) → error doesn't mention allowlist
    if result.success is False:
        assert "not in allowed_packages" not in (result.error or "")


# --- cleanup ---------------------------------------------------------------


@pytest.mark.asyncio
@_skip_if_no_uv
async def test_cleanup_agent_removes_workspace(executor):
    await executor.ensure_venv("alice")
    assert executor.agent_workspace("alice").exists()
    executor.cleanup_agent("alice")
    assert not executor.agent_workspace("alice").exists()
