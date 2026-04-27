"""Tests for polymath.tools.fs — error paths + event emission.

We don't spin up a real sandbox here. Instead we monkeypatch
``polymath.sandbox.manager.get_manager`` with a lightweight fake that
records calls and yields canned responses. The goal is to verify the
tool wrappers' contract (JSON shape, event emission, error routing),
not the SandboxManager itself — that has its own tests.
"""

from __future__ import annotations

import json
import types
from typing import Any

import pytest

from polymath import runtime as runtime_mod
from polymath.sandbox.manager import SandboxError
from polymath.state import PolymathState
from polymath.tools.fs import _edit_file, _list_dir, _read_file, _write_file


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._fs: dict[str, bytes] = {}
        self._exec_returns = (0, "", "", False)

    def _rec(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    async def put_file(self, sid: str, path: str, content: bytes) -> int:
        self._rec("put_file", sid, path, len(content))
        self._fs[path] = content
        return len(content)

    async def get_file(self, sid: str, path: str, *, max_bytes: int = 200_000):
        self._rec("get_file", sid, path, max_bytes)
        if path not in self._fs:
            raise SandboxError(f"{path} not found")
        data = self._fs[path]
        return data[:max_bytes], len(data) > max_bytes

    async def list_dir(self, sid: str, path: str = "", *, limit: int = 200):
        self._rec("list_dir", sid, path, limit)
        return [{"name": n, "path": n, "kind": "file", "size": 1} for n in self._fs], False

    async def exec(self, sid: str, cmd: list[str], *, timeout_s: float = 120.0, **kw):
        self._rec("exec", sid, tuple(cmd), timeout_s)
        return self._exec_returns


@pytest.fixture
def _fake_manager(monkeypatch: pytest.MonkeyPatch) -> _FakeManager:
    fake = _FakeManager()
    from polymath.tools import fs as fs_module

    monkeypatch.setattr(fs_module, "get_manager", lambda: fake)
    return fake


async def _run(tool_fn, state: PolymathState, **kwargs: Any) -> dict:
    ctx = types.SimpleNamespace(deps=state)
    return json.loads(await tool_fn(ctx, **kwargs))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_write_file_roundtrip(_fake_manager: _FakeManager) -> None:
    state = PolymathState(session_id="sid-1")
    result = await _run(_write_file, state, path="notes.md", content="hello")
    assert result == {"path": "notes.md", "bytes_written": 5}
    # mkdir is skipped for a root file, so only put_file should fire.
    assert any(c[0] == "put_file" for c in _fake_manager.calls)


@pytest.mark.asyncio
async def test_write_file_creates_parent_dir(_fake_manager: _FakeManager) -> None:
    state = PolymathState(session_id="sid-1")
    await _run(_write_file, state, path="nested/deep/file.txt", content="x")
    # mkdir -p … runs first when parent is non-empty.
    exec_calls = [c for c in _fake_manager.calls if c[0] == "exec"]
    assert exec_calls and exec_calls[0][1][1][0] == "mkdir"


@pytest.mark.asyncio
async def test_read_file_decodes_utf8(_fake_manager: _FakeManager) -> None:
    _fake_manager._fs["a.txt"] = "héllo 🚀".encode("utf-8")
    state = PolymathState(session_id="sid-1")
    result = await _run(_read_file, state, path="a.txt")
    assert result["text"] == "héllo 🚀"
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_read_file_binary_marker(_fake_manager: _FakeManager) -> None:
    _fake_manager._fs["a.bin"] = b"\xff\xfe\x00\x01"
    state = PolymathState(session_id="sid-1")
    result = await _run(_read_file, state, path="a.bin")
    assert result["binary"] is True
    assert result["bytes"] == 4


@pytest.mark.asyncio
async def test_read_file_missing_returns_error(_fake_manager: _FakeManager) -> None:
    state = PolymathState(session_id="sid-1")
    result = await _run(_read_file, state, path="nope.txt")
    assert "error" in result
    assert "nope.txt" in result["error"]


@pytest.mark.asyncio
async def test_edit_file_unique_match(_fake_manager: _FakeManager) -> None:
    _fake_manager._fs["a.py"] = b"x = 1\nprint(x)\n"
    state = PolymathState(session_id="sid-1")
    result = await _run(_edit_file, state, path="a.py", old="x = 1", new="x = 42")
    assert result == {"path": "a.py", "replacements": 1, "bytes_written": 16}
    assert _fake_manager._fs["a.py"].decode() == "x = 42\nprint(x)\n"


@pytest.mark.asyncio
async def test_edit_file_not_found_in_text(_fake_manager: _FakeManager) -> None:
    _fake_manager._fs["a.py"] = b"x = 1\n"
    state = PolymathState(session_id="sid-1")
    result = await _run(_edit_file, state, path="a.py", old="not-there", new="foo")
    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_edit_file_ambiguous_match(_fake_manager: _FakeManager) -> None:
    _fake_manager._fs["a.py"] = b"x = 1\nx = 1\n"
    state = PolymathState(session_id="sid-1")
    result = await _run(_edit_file, state, path="a.py", old="x = 1", new="x = 2")
    assert "error" in result
    assert "unique" in result["error"]


@pytest.mark.asyncio
async def test_list_dir_forwards_call(_fake_manager: _FakeManager) -> None:
    _fake_manager._fs.update({"a.py": b"", "b.md": b""})
    state = PolymathState(session_id="sid-1")
    result = await _run(_list_dir, state, path="", limit=10)
    assert result["path"] == ""
    assert {e["name"] for e in result["entries"]} == {"a.py", "b.md"}


@pytest.mark.asyncio
async def test_list_dir_error_shape_includes_empty_entries(
    _fake_manager: _FakeManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug #2: when the path is missing or not a directory the tool
    returns ``{path, entries: [], error}`` so the agent / frontend can
    keep iterating without a special-case branch.
    """

    async def _boom(*args, **kwargs):
        raise SandboxError("directory does not exist: ghost")

    monkeypatch.setattr(_fake_manager, "list_dir", _boom)
    state = PolymathState(session_id="sid-1")
    result = await _run(_list_dir, state, path="ghost", limit=10)
    assert result["path"] == "ghost"
    assert result["entries"] == []
    assert "directory does not exist" in result["error"]


@pytest.mark.asyncio
async def test_fs_tools_emit_sidecar_events(_fake_manager: _FakeManager) -> None:
    """Every fs tool publishes `started` + `completed` on the session bus."""
    sid = "emit-sid"
    state = PolymathState(session_id=sid)
    _fake_manager._fs["ok.txt"] = b"hi"

    rt = runtime_mod.get_runtime(sid)
    seen: list[str] = []

    async def handler(evt) -> None:
        seen.append(evt.event_type)

    rt.workbench.event_bus.subscribe_all(handler)

    await _run(_read_file, state, path="ok.txt")
    assert "tool.fs.read_file.started" in seen
    assert "tool.fs.read_file.completed" in seen
