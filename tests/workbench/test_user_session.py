"""Tests for the Docker-tier wiring on Workbench.

Critically, Workbench itself is unchanged (no breaking change). The strict
user_id + session_id requirement lives on DockerSandbox, surfaced via the
Workbench.with_docker_sandbox() factory.
"""

from __future__ import annotations

from typing import Any

import pytest

from orqest.workbench import Workbench


class _FakeMemory:
    pass


def test_workbench_unchanged_no_user_id_required():
    """Existing consumers don't need to pass user_id/session_id."""
    wb = Workbench(memory=_FakeMemory())
    assert wb.memory is not None
    # No new required fields
    assert not hasattr(wb, "user_id")
    assert not hasattr(wb, "session_id")


def test_with_docker_sandbox_requires_user_id_and_session_id():
    """The factory enforces strict user_id + session_id at the Docker
    boundary — these are keyword-only required args."""
    wb = Workbench(memory=_FakeMemory())
    with pytest.raises(TypeError, match="user_id"):
        wb.with_docker_sandbox(session_id="x")  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="session_id"):
        wb.with_docker_sandbox(user_id="alice")  # type: ignore[call-arg]


def test_with_docker_sandbox_returns_unstarted_sandbox(monkeypatch):
    """Construction alone doesn't run docker — DockerSandbox is an async
    context manager that runs the container in __aenter__."""
    captured: dict[str, Any] = {}

    class _FakeDockerSandbox:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "orqest.sandbox.docker.DockerSandbox", _FakeDockerSandbox
    )

    wb = Workbench(memory=_FakeMemory())
    sb = wb.with_docker_sandbox(
        user_id="alice",
        session_id="session-1",
        image="custom:tag",
        allowed_packages={"pandas"},
    )
    assert captured["user_id"] == "alice"
    assert captured["session_id"] == "session-1"
    assert captured["image"] == "custom:tag"
    assert captured["allowed_packages"] == {"pandas"}
    # Bus auto-wired from the workbench
    assert captured["bus"] is wb.event_bus
    assert sb is not None  # We got the (fake) DockerSandbox back


def test_with_docker_sandbox_defaults(monkeypatch):
    """Defaults match the documented values."""
    captured: dict[str, Any] = {}

    class _FakeDockerSandbox:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "orqest.sandbox.docker.DockerSandbox", _FakeDockerSandbox
    )

    wb = Workbench(memory=_FakeMemory())
    wb.with_docker_sandbox(user_id="alice", session_id="x")
    assert captured["image"] == "orqest/agent-runtime:latest"
    assert captured["allowed_packages"] is None  # default-deny — empty meaningful
    assert captured["memory_mb"] == 2048
    assert captured["cpus"] == 2.0
    assert captured["pids_limit"] == 512
    assert captured["promotion_policy"] == "threshold"
    assert captured["promotion_threshold"] == 3
