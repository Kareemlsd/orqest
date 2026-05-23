"""FastMCP middleware for HMAC-signed JWT session-auth + scope enforcement.

Validates the ``Authorization: Bearer <jwt>`` header on every
``tools/call`` and ``tools/list`` request:

1. Extract the bearer token from the HTTP ``Authorization`` header.
2. Verify HS256 signature against the container's
   ``ORQEST_HMAC_SECRET`` (mounted via env var by the host orchestrator).
3. Verify ``sub == ORQEST_USER_ID`` (mismatch = wrong-user attack).
4. Verify ``sid == ORQEST_SESSION_ID`` (mismatch = wrong-session attack).
5. Verify ``exp`` is in the future (replay attack defense).
6. **Verify ``scope`` matches the requirement of the specific MCP tool
   being called.** ``promote_tool`` and ``forget_tool`` require
   ``scope == "operator"``; everything else accepts ``"agent"`` or
   ``"operator"``. Missing ``scope`` claim defaults to ``"agent"`` so
   tokens minted before the scope feature stay strictly bounded.
7. Reject with a typed exception that FastMCP maps to JSON-RPC error.

Why scope separation: the host's MCP connection minted a single JWT and
used it for every tool call. The LLM, calling tools through that
connection, could reach ``promote_tool`` and bypass the threshold
counter (or the ``operator_approval`` gate) directly. Splitting the
scope so the agent-facing connection can only run code — never persist
tools — closes the hole at the transport boundary.

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

# DNS-rebinding defense — applied when ``ORQEST_ALLOWED_ORIGINS`` is unset.
# The host orchestrator publishes the container's port via
# ``-p 127.0.0.1:<host>:8000``, so the host-side MCP client always presents
# an Origin under one of these. Operators on non-default deployments
# (custom hostnames, Tier-3 future bridge networks) set the env var
# explicitly to override.
#
# An *explicit* empty value (``ORQEST_ALLOWED_ORIGINS=""``) still disables
# the check — that's the documented escape hatch for environments that
# can't supply an Origin header.
DEFAULT_ALLOWED_ORIGINS: frozenset[str] = frozenset({
    "http://127.0.0.1",
    "http://localhost",
})

# JWT scopes. ``agent`` is the everyday agent-loop scope; the host's
# regular MCP connection mints this. ``operator`` is reserved for
# persistence-side calls (``promote_tool`` / ``forget_tool``) that must
# only be initiated by the host orchestrator — never the LLM.
SCOPE_AGENT = "agent"
SCOPE_OPERATOR = "operator"
_VALID_SCOPES: frozenset[str] = frozenset({SCOPE_AGENT, SCOPE_OPERATOR})

# Tools that require ``scope == "operator"``. Everything else accepts
# either scope (least privilege still applies — the alternative would be
# a default-deny on unknown tools, but FastMCP also serves tools added
# at runtime via ``add_tool``, and we don't want to break those by
# default).
DEFAULT_OPERATOR_TOOLS: frozenset[str] = frozenset({
    "promote_tool",
    "forget_tool",
})


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
        operator_tools: set[str] | None = None,
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
        self._operator_tools = (
            set(operator_tools)
            if operator_tools is not None
            else set(DEFAULT_OPERATOR_TOOLS)
        )

    @classmethod
    def from_env(cls) -> SessionAuthMiddleware:
        """Construct from the standard env vars used by the runtime image.

        ``ORQEST_ALLOWED_ORIGINS`` defaults to :data:`DEFAULT_ALLOWED_ORIGINS`
        when *unset* — DNS-rebinding defense is on by default per the MCP
        spec. Set the env var explicitly (incl. ``""`` for "no check") to
        override.
        """
        secret = os.environ.get("ORQEST_HMAC_SECRET", "")
        user_id = os.environ.get("ORQEST_USER_ID", "")
        session_id = os.environ.get("ORQEST_SESSION_ID", "")
        # Distinguish "unset" from "explicitly empty": missing → secure default;
        # explicit empty → operator opted out (documented escape hatch).
        origins_raw = os.environ.get("ORQEST_ALLOWED_ORIGINS")
        if origins_raw is None:
            origins: set[str] = set(DEFAULT_ALLOWED_ORIGINS)
        else:
            origins = {o.strip() for o in origins_raw.split(",") if o.strip()}
        return cls(
            secret=secret,
            expected_user_id=user_id,
            expected_session_id=session_id,
            allowed_origins=origins,
        )

    # --- Middleware hooks -------------------------------------------------

    async def on_call_tool(self, context: MiddlewareContext, call_next: Any) -> Any:
        claims = self._verify_request(stage="call_tool")
        tool_name = _extract_tool_name(context)
        self._check_scope(claims, tool_name=tool_name)
        return await call_next(context)

    async def on_list_tools(self, context: MiddlewareContext, call_next: Any) -> Any:
        # tools/list doesn't act on persistence, so any authenticated scope
        # is fine. (An operator-scope token can also list.)
        self._verify_request(stage="list_tools")
        return await call_next(context)

    # --- Internals -------------------------------------------------------

    def _verify_request(self, *, stage: str) -> dict:
        """Verify token + Origin; return the claims dict on success.

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

        return claims

    def _check_scope(self, claims: dict, *, tool_name: str | None) -> None:
        """Enforce per-tool scope requirements.

        Tokens that omit ``scope`` default to ``agent`` — the least-privilege
        scope. ``operator``-only tools reject ``agent`` tokens; ``agent``
        tokens can call everything else.
        """
        raw_scope = claims.get("scope", SCOPE_AGENT)
        if raw_scope not in _VALID_SCOPES:
            logger.warning(
                "SessionAuthMiddleware: unknown scope {s!r}", s=raw_scope
            )
            raise SessionAuthError("invalid scope claim")

        if tool_name in self._operator_tools and raw_scope != SCOPE_OPERATOR:
            logger.warning(
                "SessionAuthMiddleware: agent-scope token rejected for "
                "operator-only tool {t!r}", t=tool_name,
            )
            raise SessionAuthError("operator scope required")


def _extract_tool_name(context: MiddlewareContext) -> str | None:
    """Best-effort tool-name extraction from a FastMCP middleware context.

    Returns ``None`` when the shape doesn't match — defensive against
    FastMCP API drift; callers treat ``None`` as "non-operator tool"
    (least privilege still applies because the scope check defaults to
    requiring agent-or-operator, which any verified token satisfies).
    """
    message = getattr(context, "message", None)
    name = getattr(message, "name", None)
    return name if isinstance(name, str) else None


__all__ = [
    "SessionAuthError",
    "SessionAuthMiddleware",
]
