"""Tests for orqest.sandbox._identifiers — path-traversal hardening."""

from __future__ import annotations

import pytest

from orqest.sandbox._identifiers import check_identifier, is_valid_identifier


# --- valid shapes -----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "alice",
        "user-1",
        "session_xyz",
        "abc123",
        "1abc",  # digit start is fine
        "a" * 64,  # max length
        "agent-9_42",
    ],
)
def test_accepts_valid_identifier(name: str) -> None:
    assert is_valid_identifier(name)
    check_identifier(name, kind="test")  # no raise


# --- invalid shapes ---------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "",                       # empty
        "_starts_with_underscore", # leading underscore not allowed (start must be alphanum)
        "-starts-with-dash",       # leading dash
        "../etc/passwd",           # path traversal
        "../../tmp/leak",          # path traversal
        "/absolute/path",
        "with space",
        "with.dot",
        "with/slash",
        "with\\backslash",
        "with:colon",
        "with;semi",
        "with$dollar",
        "with`backtick",
        "with\nnewline",
        "with\ttab",
        "a" * 65,                  # too long
        "café",                    # unicode rejected
    ],
)
def test_rejects_invalid_identifier(name: str) -> None:
    assert not is_valid_identifier(name)
    with pytest.raises(ValueError, match="invalid test"):
        check_identifier(name, kind="test")


def test_rejects_non_string() -> None:
    assert not is_valid_identifier(None)  # type: ignore[arg-type]
    assert not is_valid_identifier(42)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        check_identifier(None, kind="test")  # type: ignore[arg-type]


# --- wiring into the host-side DockerSandbox --------------------------------


def test_docker_sandbox_rejects_traversal_user_id() -> None:
    from orqest.sandbox.docker import DockerSandbox

    with pytest.raises(ValueError, match="invalid user_id"):
        DockerSandbox(user_id="../etc", session_id="abc")


def test_docker_sandbox_rejects_traversal_session_id() -> None:
    from orqest.sandbox.docker import DockerSandbox

    with pytest.raises(ValueError, match="invalid session_id"):
        DockerSandbox(user_id="alice", session_id="../leak")


# --- wiring into the in-container Executor ----------------------------------


@pytest.mark.asyncio
async def test_executor_rejects_traversal_agent_id(tmp_path) -> None:
    from orqest.sandbox.docker_runtime.executor import Executor, ExecutorConfig

    executor = Executor(ExecutorConfig(
        workspace_root=tmp_path,
        session_id="sess-1",
        allowed_packages=frozenset(),
    ))

    result = await executor.execute(
        code="return 1",
        args={},
        allowed_imports=set(),
        agent_id="../escape",
    )
    assert result.success is False
    assert "invalid agent_id" in result.error
