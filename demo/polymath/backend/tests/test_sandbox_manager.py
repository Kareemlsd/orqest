"""Tests for the SandboxManager's pure-logic bits (path safety, lazy client)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from polymath.sandbox.manager import SandboxError, SandboxManager


def test_safe_path_rejects_absolute() -> None:
    m = SandboxManager()
    with pytest.raises(SandboxError, match="absolute"):
        m._safe_path("/etc/passwd")


def test_safe_path_rejects_traversal() -> None:
    m = SandboxManager()
    with pytest.raises(SandboxError, match="traversal"):
        m._safe_path("../../etc/passwd")


def test_safe_path_accepts_relative() -> None:
    m = SandboxManager()
    assert m._safe_path("notes/todo.md") == "notes/todo.md"


def test_safe_path_strips_dot_components() -> None:
    m = SandboxManager()
    assert m._safe_path("./sub/./file.txt") == "sub/file.txt"


def test_safe_path_empty_returns_empty() -> None:
    m = SandboxManager()
    assert m._safe_path("") == ""


def test_container_name_and_volume_name_use_session_id() -> None:
    m = SandboxManager()
    assert m._container_name("abc") == "polymath-session-abc"
    assert m._volume_name("abc") == "polymath-session-abc"


def test_lazy_client_not_built_until_used() -> None:
    """Constructing a SandboxManager must not eagerly contact the docker daemon."""
    m = SandboxManager()
    assert m._client is None


# ---------- list_dir parsing — Bug #2 fix ----------
#
# These tests exercise the manager's response-parsing layer directly,
# without spinning up a real container. The script execution is mocked
# at ``manager.exec`` so the test runs in milliseconds.


class _ExecStub:
    """Records the last exec invocation and returns a canned result."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.last_args: tuple[Any, ...] | None = None

    async def __call__(
        self, session_id: str, cmd: list[str], **_: Any
    ) -> tuple[int, str, str, bool]:
        self.last_args = (session_id, cmd)
        return self.returncode, self.stdout, self.stderr, False


@pytest.mark.asyncio
async def test_list_dir_returns_rows_when_status_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = SandboxManager()
    payload = {
        "status": "ok",
        "rows": [
            {"name": "a.py", "path": "a.py", "kind": "file", "size": 1, "mtime": 0},
        ],
        "total": 1,
    }
    stub = _ExecStub(stdout=json.dumps(payload))
    monkeypatch.setattr(m, "exec", stub)
    rows, truncated = await m.list_dir("sid", "")
    assert truncated is False
    assert rows[0]["name"] == "a.py"


@pytest.mark.asyncio
async def test_list_dir_treats_root_workspace_missing_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand-new sandbox that has never had a write may not have
    ``/workspace`` materialized yet; the agent should see an empty list
    rather than a hard error for the workspace root."""
    m = SandboxManager()
    payload = {"status": "missing", "path": "/workspace"}
    stub = _ExecStub(stdout=json.dumps(payload))
    monkeypatch.setattr(m, "exec", stub)
    rows, truncated = await m.list_dir("sid", "")
    assert rows == []
    assert truncated is False


@pytest.mark.asyncio
async def test_list_dir_raises_when_subpath_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug #2: any non-root missing path should raise so the agent
    knows the difference between *empty* and *wrong path*."""
    m = SandboxManager()
    payload = {"status": "missing", "path": "/workspace/ghost"}
    stub = _ExecStub(stdout=json.dumps(payload))
    monkeypatch.setattr(m, "exec", stub)
    with pytest.raises(SandboxError, match="does not exist"):
        await m.list_dir("sid", "ghost")


@pytest.mark.asyncio
async def test_list_dir_raises_when_target_is_a_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug #2: pointing list_dir at a file (not a dir) should raise."""
    m = SandboxManager()
    payload = {"status": "not_a_directory", "path": "/workspace/f.txt"}
    stub = _ExecStub(stdout=json.dumps(payload))
    monkeypatch.setattr(m, "exec", stub)
    with pytest.raises(SandboxError, match="not a directory"):
        await m.list_dir("sid", "f.txt")


@pytest.mark.asyncio
async def test_list_dir_raises_on_unparseable_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: stale or noisy stdout should not crash with a generic KeyError."""
    m = SandboxManager()
    stub = _ExecStub(stdout="not-json-at-all")
    monkeypatch.setattr(m, "exec", stub)
    with pytest.raises(SandboxError, match="unparseable"):
        await m.list_dir("sid", "")


@pytest.mark.asyncio
async def test_list_dir_truncates_to_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    m = SandboxManager()
    rows = [
        {"name": f"f{i}.txt", "path": f"f{i}.txt", "kind": "file", "size": 0, "mtime": 0}
        for i in range(5)
    ]
    payload = {"status": "ok", "rows": rows, "total": 5}
    stub = _ExecStub(stdout=json.dumps(payload))
    monkeypatch.setattr(m, "exec", stub)
    out_rows, truncated = await m.list_dir("sid", "", limit=3)
    assert len(out_rows) == 3
    assert truncated is True
