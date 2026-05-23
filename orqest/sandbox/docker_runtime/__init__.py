"""``orqest.sandbox.docker_runtime`` — runs INSIDE the Docker container.

This package is the body of the published ``orqest/agent-runtime`` image.
The host-side :class:`orqest.sandbox.docker.DockerSandbox` runs the image
with::

    python -m orqest.sandbox.docker_runtime

which boots a FastMCP server bound to ``0.0.0.0:8000`` (Streamable HTTP).

Modules:

* :mod:`store` — SQLite-backed persistence for runtime-promoted tools,
  scoped to a single user (mounted as ``orqest-user-<user_id>:/data``).
* :mod:`executor` — actual code execution: per-agent ``.venv`` via ``uv``,
  ``uv pip install`` for declared dependencies (gated by allowed_packages),
  subprocess into the venv with stdin/stdout JSON.
* :mod:`auth` — FastMCP middleware that validates the HMAC-signed JWT
  bearer token on every ``tools/call`` and ``tools/list``.
* :mod:`server` — wires the four built-in tools (``execute_python``,
  ``promote_tool``, ``list_persisted_tools``, ``forget_tool``), replays
  the persisted library on startup, fires
  ``notifications/tools/list_changed`` on promotion.
* :mod:`__main__` — env-driven entry point. Reads ``ORQEST_USER_ID``,
  ``ORQEST_SESSION_ID``, ``ORQEST_HMAC_SECRET``, ``ORQEST_ALLOWED_PACKAGES``,
  ``ORQEST_PROMOTION_POLICY``, ``ORQEST_PROMOTION_THRESHOLD``. Refuses to
  start if required vars missing.
"""
