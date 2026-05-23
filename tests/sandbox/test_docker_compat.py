"""Tests for the ``orqest.sandbox._compat`` soft-import boundary.

The boundary lets the rest of orqest (and its tests) import without
requiring the optional ``docker`` SDK. Failure mode when the SDK is
missing is a friendly :class:`ImportError` raised at first call to
``docker_from_env()`` / ``docker_errors()``, not at module load.
"""

from __future__ import annotations

import sys
from importlib import reload
from unittest.mock import patch

import pytest

import orqest.sandbox._compat as compat


def test_module_imports_without_error():
    """Importing the compat module never raises, even if docker missing."""
    assert hasattr(compat, "docker_from_env")
    assert hasattr(compat, "docker_errors")
    assert hasattr(compat, "DOCKER_AVAILABLE")


def test_available_flag_matches_actual_import():
    """DOCKER_AVAILABLE reflects whether ``docker`` is importable."""
    try:
        import docker  # noqa: F401
        expected = True
    except ImportError:
        expected = False
    assert compat.DOCKER_AVAILABLE is expected


def test_docker_from_env_raises_friendly_error_when_missing():
    """When SDK is absent, the call site gets the install hint."""
    with patch.object(compat, "DOCKER_AVAILABLE", False), \
         patch.object(compat, "_docker_sdk", None):
        with pytest.raises(ImportError, match="docker.*dependency group"):
            compat.docker_from_env()


def test_docker_errors_raises_friendly_error_when_missing():
    with patch.object(compat, "DOCKER_AVAILABLE", False), \
         patch.object(compat, "_docker_sdk", None):
        with pytest.raises(ImportError, match="docker.*dependency group"):
            compat.docker_errors()


def test_docker_sandbox_import_does_not_require_sdk():
    """Importing :mod:`orqest.sandbox.docker` works even without the SDK.

    The SDK is only consulted inside ``__aenter__`` / ``__aexit__``,
    so the class is constructable + tests can be collected without it.
    """
    # Pop the module so reload sees a fresh import path
    sys.modules.pop("orqest.sandbox.docker", None)
    with patch.object(compat, "DOCKER_AVAILABLE", False), \
         patch.object(compat, "_docker_sdk", None):
        import orqest.sandbox.docker as docker_mod  # noqa: F401
        assert hasattr(docker_mod, "DockerSandbox")
        assert hasattr(docker_mod, "DockerSandboxError")
        assert hasattr(docker_mod, "DockerImageNotFoundError")
