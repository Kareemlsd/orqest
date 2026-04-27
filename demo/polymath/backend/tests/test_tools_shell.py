"""Tests for polymath.tools.shell — event emission + exit-code routing."""

from __future__ import annotations

import json
import types
from typing import Any

import pytest

from polymath import runtime as runtime_mod
from polymath.sandbox.manager import SandboxError
from polymath.state import PolymathState
from polymath.tools.shell import _run_command, _run_python_snippet


class _FakeManager:
    def __init__(self, returns: tuple[int, str, str, bool] = (0, "ok\n", "", False)) -> None:
        self.returns = returns
        self.calls: list[tuple[Any, ...]] = []

    async def exec(self, sid: str, cmd: list[str], *, timeout_s: float = 120.0, **kw):
        self.calls.append((sid, tuple(cmd), timeout_s))
        return self.returns


@pytest.fixture
def _fake_manager(monkeypatch: pytest.MonkeyPatch) -> _FakeManager:
    fake = _FakeManager()
    from polymath.tools import shell as shell_module

    monkeypatch.setattr(shell_module, "get_manager", lambda: fake)
    return fake


async def _run(tool_fn, state: PolymathState, **kwargs: Any) -> dict:
    ctx = types.SimpleNamespace(deps=state)
    return json.loads(await tool_fn(ctx, **kwargs))


@pytest.mark.asyncio
async def test_run_command_success_shape(_fake_manager: _FakeManager) -> None:
    state = PolymathState(session_id="sid-a")
    result = await _run(_run_command, state, command="echo hi")
    assert result == {"exit_code": 0, "stdout": "ok\n", "stderr": "", "truncated": False}
    sid, cmd, _ = _fake_manager.calls[0]
    assert sid == "sid-a"
    assert cmd == ("bash", "-lc", "echo hi")


@pytest.mark.asyncio
async def test_run_command_returns_nonzero(_fake_manager: _FakeManager) -> None:
    _fake_manager.returns = (1, "", "oops\n", False)
    state = PolymathState(session_id="sid-b")
    result = await _run(_run_command, state, command="false")
    assert result["exit_code"] == 1
    assert "oops" in result["stderr"]


@pytest.mark.asyncio
async def test_run_command_sandbox_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadManager:
        async def exec(self, *a, **kw):
            raise SandboxError("no docker")

    from polymath.tools import shell as shell_module

    monkeypatch.setattr(shell_module, "get_manager", lambda: _BadManager())
    state = PolymathState(session_id="sid-c")
    result = await _run(_run_command, state, command="echo x")
    assert result == {"error": "no docker", "exit_code": -1}


@pytest.mark.asyncio
async def test_run_python_snippet_wraps_exec(_fake_manager: _FakeManager) -> None:
    _fake_manager.returns = (0, "hello\n", "", False)
    state = PolymathState(session_id="sid-d")
    result = await _run(_run_python_snippet, state, code="print('hello')")
    assert result["exit_code"] == 0
    assert result["stdout"] == "hello\n"
    assert _fake_manager.calls[0][1] == ("python3", "-c", "print('hello')")


@pytest.mark.asyncio
async def test_run_command_emits_stdout_event(_fake_manager: _FakeManager) -> None:
    sid = "emit-shell"
    state = PolymathState(session_id=sid)
    rt = runtime_mod.get_runtime(sid)
    seen: list[str] = []

    async def handler(evt) -> None:
        seen.append(evt.event_type)

    rt.workbench.event_bus.subscribe_all(handler)
    await _run(_run_command, state, command="echo hi")
    assert "tool.shell.run_command.started" in seen
    assert "shell.stdout" in seen
    assert "tool.shell.run_command.completed" in seen
