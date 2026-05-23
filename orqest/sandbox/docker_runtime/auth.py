"""FastMCP middleware for HMAC-signed JWT session-auth.

Validates the ``Authorization: Bearer <jwt>`` header on every
``tools/call`` and ``tools/list`` request:

1. Extract the bearer token from the HTTP ``Authorization`` header.
2. Verify HS256 signature against the container's
   ``ORQEST_HMAC_SECRET`` (mounted via env var by the host orchestrator).
3. Verify ``sub == ORQEST_USER_ID`` (mismatch = wrong-user attack).
4. Verify ``sid == ORQEST_SESSION_ID`` (mismatch = wrong-session attack).
5. Verify ``exp`` is in the future (replay attack defense).
6. Reject with a typed exception that FastMCP maps to JSON-RPC error.

Origin header validation (DNS-rebinding defense per MCP spec) is
delegated to the underlying transport layer (Starlette/uvicorn handles
``allowed_hosts``), but we additionally check that ``Origin`` if present
matches an expected host — see ``ORQEST_ALLOWED_ORIGINS``.

The middleware is fail-closed: missing token / malformed token / any
verification failure rejects with PermissionError. The LLM-controlled
side never sees the rejection details — it sees ``isError: true`` with
a generic "authentication failed" message.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext
from loguru import logger

from orqest.sandbox.jwt import (
    JWTError,
)
from orqest.sandbox.jwt import (
    decode as jwt_decode,
)

_BEARER_PREFIX = "Bearer "


class SessionAuthError(PermissionError):
    """Raised when a request fails session-auth validation.

    Inherits PermissionError so FastMCP maps it to JSON-RPC 'permission denied'.
    """


class SessionAuthMiddleware(Middleware):
    """JWT session-auth for the in-container FastMCP server.

    Construction reads the auth context from env vars (so the host
    orchestrator controls all of: who the user is, which session this
    container serves, and the shared HMAC secret).

    Args:
        secret: HMAC secret from ``ORQEST_HMAC_SECRET``.
        expected_user_id: From ``ORQEST_USER_ID``.
        expected_session_id: From ``ORQEST_SESSION_ID``.
        allowed_origins: Optional set of expected Origin header values
            (DNS-rebinding defense). Empty = don't check Origin.

    """

    def __init__(
        self,
        *,
        secret: str | bytes,
        expected_user_id: str,
        expected_session_id: str,
        allowed_origins: set[str] | None = None,
    ) -> None:
        if not secret:
            raise ValueError("HMAC secret is required (non-empty)")
        if not expected_user_id:
            raise ValueError("expected_user_id is required (non-empty)")
        if not expected_session_id:
            raise ValueError("expected_session_id is required (non-empty)")
        self._secret = secret
        self._expected_user_id = expected_user_id
        self._expected_session_id = expected_session_id
        self._allowed_origins = allowed_origins or set()

    @classmethod
    def from_env(cls) -> SessionAuthMiddleware:
        """Construct from the standard env vars used by the runtime image."""
        secret = os.environ.get("ORQEST_HMAC_SECRET", "")
        user_id = os.environ.get("ORQEST_USER_ID", "")
        session_id = os.environ.get("ORQEST_SESSION_ID", "")
        origins_raw = os.environ.get("ORQEST_ALLOWED_ORIGINS", "")
        origins = {o.strip() for o in origins_raw.split(",") if o.strip()}
        return cls(
            secret=secret,
            expected_user_id=user_id,
            expected_session_id=session_id,
            allowed_origins=origins,
        )

    # --- Middleware hooks -------------------------------------------------

    async def on_call_tool(self, context: MiddlewareContext, call_next: Any) -> Any:
        self._validate_request(stage="call_tool")
        return await call_next(context)

    async def on_list_tools(self, context: MiddlewareContext, call_next: Any) -> Any:
        self._validate_request(stage="list_tools")
        return await call_next(context)

    # --- Internals -------------------------------------------------------

    def _validate_request(self, *, stage: str) -> None:
        """Pull the bearer + Origin from the current HTTP request and verify.

        Lazy-imports ``get_http_headers`` from FastMCP — only available
        at request time. If we're called outside an HTTP context (e.g.
        a stdio test) we fail closed.
        """
        try:
            from fastmcp.server.dependencies import get_http_headers
            headers = get_http_headers()
        except RuntimeError as exc:
            # Not inside an HTTP request — fail closed
            logger.warning(
                "SessionAuthMiddleware: not in HTTP context at {s}: {e}",
                s=stage, e=exc,
            )
            raise SessionAuthError("auth context unavailable") from exc

        # Origin check (only if allowed_origins configured)
        if self._allowed_origins:
            origin = headers.get("origin", "")
            if origin and origin not in self._allowed_origins:
                logger.warning(
                    "SessionAuthMiddleware: rejected origin {o!r} at {s}",
                    o=origin, s=stage,
                )
                raise SessionAuthError("origin not allowed")

        # Authorization: Bearer <jwt>
        auth = headers.get("authorization", "")
        if not auth.startswith(_BEARER_PREFIX):
            logger.warning(
                "SessionAuthMiddleware: missing Bearer at {s}", s=stage
            )
            raise SessionAuthError("missing bearer token")
        token = auth[len(_BEARER_PREFIX):].strip()
        if not token:
            raise SessionAuthError("empty bearer token")

        # JWT verify (signature + exp)
        try:
            claims = jwt_decode(token, self._secret)
        except JWTError as exc:
            logger.warning(
                "SessionAuthMiddleware: JWT verification failed at {s}: {e}",
                s=stage, e=exc,
            )
            raise SessionAuthError("invalid bearer token") from exc

        # sub / sid match
        sub = claims.get("sub", "")
        sid = claims.get("sid", "")
        if sub != self._expected_user_id:
            logger.warning(
                "SessionAuthMiddleware: sub mismatch (expected {exp!r}, got {got!r}) at {s}",
                exp=self._expected_user_id, got=sub, s=stage,
            )
            raise SessionAuthError("user_id mismatch")
        if sid != self._expected_session_id:
            logger.warning(
                "SessionAuthMiddleware: sid mismatch at {s}", s=stage
            )
            raise SessionAuthError("session_id mismatch")


__all__ = [
    "SessionAuthError",
    "SessionAuthMiddleware",
]
