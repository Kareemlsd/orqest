"""Entry point for the orqest/agent-runtime container.

Boots the FastMCP server with auth + executor + persistence, binding to
``0.0.0.0:8000`` (Streamable HTTP transport). The host orchestrator
publishes a port via ``-p 127.0.0.1:<host>:8000``.

Required env vars:

* ``ORQEST_USER_ID``         — strict per-user identifier (persistence boundary)
* ``ORQEST_SESSION_ID``      — strict per-session identifier (lifecycle key)
* ``ORQEST_HMAC_SECRET``     — HMAC key for JWT signature verification

Optional env vars:

* ``ORQEST_ALLOWED_PACKAGES`` — comma-separated PyPI package allowlist
  (default empty = all installs blocked, but stdlib code still works)
* ``ORQEST_PROMOTION_POLICY`` — ``"threshold"`` (default) | ``"eager"`` |
  ``"operator_approval"``
* ``ORQEST_PROMOTION_THRESHOLD`` — N successful invocations before
  threshold-mode auto-promotion (default 3)
* ``ORQEST_TOOLS_DB`` — SQLite path (default ``/data/orqest-tools.sqlite``)
* ``ORQEST_ALLOWED_ORIGINS`` — comma-separated Origin header allowlist
  (DNS-rebinding defense). When **unset**, defaults to
  ``http://127.0.0.1,http://localhost``. Set explicitly (incl. ``""``
  for "no check") to override.
* ``ORQEST_HOST`` — bind host (default ``0.0.0.0``)
* ``ORQEST_PORT`` — bind port (default ``8000``)
"""

from __future__ import annotations

import os
import sys

from loguru import logger

from orqest.sandbox.docker_runtime.server import build_server_from_env


def main() -> int:
    try:
        mcp = build_server_from_env()
    except Exception as exc:  # noqa: BLE001
        logger.error("orqest-agent-runtime startup failed: {e}", e=exc)
        return 1

    host = os.environ.get("ORQEST_HOST", "0.0.0.0")  # noqa: S104 — container scope
    try:
        port = int(os.environ.get("ORQEST_PORT", "8000"))
    except ValueError:
        logger.error("ORQEST_PORT must be an integer")
        return 1

    logger.info(
        "orqest-agent-runtime starting on {h}:{p} (user={u}, session={s})",
        h=host, p=port,
        u=os.environ.get("ORQEST_USER_ID", "?"),
        s=os.environ.get("ORQEST_SESSION_ID", "?")[:8] + "…",
    )
    # FastMCP's run() blocks; transport "streamable-http" matches what the
    # host-side MCPConnection connects to.
    mcp.run(transport="streamable-http", host=host, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
