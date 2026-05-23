"""Soft-import boundary for the optional ``docker`` SDK.

The Tier-2 :class:`DockerSandbox` needs the ``docker`` Python SDK on the
host. Subprocess + InProcess tiers stay dependency-free. Mirrors the
pattern used by ``orqest.optimization._compat`` for the GEPA library.

Install with:

    uv sync --group docker

When the SDK is missing, ``docker_from_env()`` raises ``ImportError`` with
the install command in the message — friendly compared to the default
``ModuleNotFoundError: No module named 'docker'``.
"""

from __future__ import annotations

from typing import Any

_INSTALL_HINT = (
    "DockerSandbox requires the 'docker' dependency group: "
    "uv sync --group docker"
)

try:
    import docker as _docker_sdk
    DOCKER_AVAILABLE = True
    _IMPORT_ERR: ImportError | None = None
except ImportError as exc:
    DOCKER_AVAILABLE = False
    _IMPORT_ERR = exc
    _docker_sdk = None  # type: ignore[assignment]


def docker_from_env(*args: Any, **kwargs: Any) -> Any:
    """Return ``docker.from_env(...)`` or raise a friendly :class:`ImportError`.

    Use this instead of ``import docker; docker.from_env()`` so the missing
    dep produces the install hint at first call (not at import time).
    """
    if not DOCKER_AVAILABLE:
        raise ImportError(_INSTALL_HINT) from _IMPORT_ERR
    return _docker_sdk.from_env(*args, **kwargs)  # type: ignore[union-attr]


def docker_errors() -> Any:
    """Return the ``docker.errors`` module, or raise the friendly ImportError."""
    if not DOCKER_AVAILABLE:
        raise ImportError(_INSTALL_HINT) from _IMPORT_ERR
    return _docker_sdk.errors  # type: ignore[union-attr]


__all__ = [
    "DOCKER_AVAILABLE",
    "docker_errors",
    "docker_from_env",
]
