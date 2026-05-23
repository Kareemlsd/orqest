"""Tests for JWT scope separation in SessionAuthMiddleware.

The host-side ``DockerSandbox`` mints ``agent``-scope tokens for the
agent-facing MCP connection. ``promote_tool`` and ``forget_tool`` are
configured as operator-only, so an agent-scope token can no longer
bypass the threshold counter or the operator_approval gate.
"""

from __future__ import annotations

import time

import pytest

from orqest.sandbox.docker_runtime.auth import (
    DEFAULT_OPERATOR_TOOLS,
    SCOPE_AGENT,
    SCOPE_OPERATOR,
    SessionAuthError,
    SessionAuthMiddleware,
)
from orqest.sandbox.jwt import encode as jwt_encode

SECRET = "0" * 64
USER = "alice"
SID = "session-abc123"


def _token(*, scope: str | None = SCOPE_AGENT, exp_offset: int = 60):
    claims: dict = {"sub": USER, "sid": SID, "exp": int(time.time()) + exp_offset}
    if scope is not None:
        claims["scope"] = scope
    return jwt_encode(claims, SECRET)


@pytest.fixture
def mw() -> SessionAuthMiddleware:
    return SessionAuthMiddleware(
        secret=SECRET,
        expected_user_id=USER,
        expected_session_id=SID,
    )


# --- The scope check itself -------------------------------------------------


class TestScopeCheck:
    def test_agent_scope_allowed_on_non_operator_tool(self, mw):
        claims = {"scope": SCOPE_AGENT}
        mw._check_scope(claims, tool_name="execute_python")  # no raise

    def test_operator_scope_allowed_on_non_operator_tool(self, mw):
        claims = {"scope": SCOPE_OPERATOR}
        mw._check_scope(claims, tool_name="execute_python")  # no raise

    def test_agent_scope_rejected_on_operator_tool(self, mw):
        claims = {"scope": SCOPE_AGENT}
        with pytest.raises(SessionAuthError, match="operator scope required"):
            mw._check_scope(claims, tool_name="promote_tool")

    def test_agent_scope_rejected_on_forget_tool(self, mw):
        claims = {"scope": SCOPE_AGENT}
        with pytest.raises(SessionAuthError, match="operator scope required"):
            mw._check_scope(claims, tool_name="forget_tool")

    def test_operator_scope_allowed_on_operator_tool(self, mw):
        claims = {"scope": SCOPE_OPERATOR}
        mw._check_scope(claims, tool_name="promote_tool")  # no raise

    def test_missing_scope_defaults_to_agent(self, mw):
        """Tokens minted before the scope feature shipped (no ``scope`` claim)
        are treated as agent-scope — least privilege."""
        claims: dict = {}
        # OK on agent-callable tools…
        mw._check_scope(claims, tool_name="execute_python")
        # …but rejected on operator-only tools.
        with pytest.raises(SessionAuthError, match="operator scope required"):
            mw._check_scope(claims, tool_name="promote_tool")

    def test_unknown_scope_rejected(self, mw):
        claims = {"scope": "root"}
        with pytest.raises(SessionAuthError, match="invalid scope"):
            mw._check_scope(claims, tool_name="execute_python")

    def test_none_tool_name_does_not_enforce_operator(self, mw):
        """Defensive — if FastMCP context shape changes and ``tool_name``
        comes back as None, we still let any verified token through (the
        on_call_tool hook already required token validity)."""
        claims = {"scope": SCOPE_AGENT}
        mw._check_scope(claims, tool_name=None)  # no raise


# --- Custom operator_tools set ---------------------------------------------


def test_custom_operator_tools_override_default():
    mw = SessionAuthMiddleware(
        secret=SECRET,
        expected_user_id=USER,
        expected_session_id=SID,
        operator_tools={"my_custom_tool"},
    )
    # promote_tool no longer operator-only when custom set is provided
    mw._check_scope({"scope": SCOPE_AGENT}, tool_name="promote_tool")
    # but my_custom_tool is
    with pytest.raises(SessionAuthError, match="operator scope required"):
        mw._check_scope({"scope": SCOPE_AGENT}, tool_name="my_custom_tool")


def test_default_operator_tools_contains_expected_set():
    assert "promote_tool" in DEFAULT_OPERATOR_TOOLS
    assert "forget_tool" in DEFAULT_OPERATOR_TOOLS


# --- Host-side mint_operator_token path ------------------------------------


def test_docker_sandbox_mint_operator_token_emits_operator_scope():
    """The host orchestrator can mint operator-scope tokens for
    promote_tool / forget_tool calls; the LLM-facing connection still uses
    agent scope, so the separation holds."""
    from orqest.sandbox.docker import DockerSandbox
    from orqest.sandbox.jwt import decode as jwt_decode

    # Construct without entering the context manager — we only exercise
    # the host-side token-minting helpers.
    sb = DockerSandbox(
        user_id="alice",
        session_id="sess-12345",
        hmac_secret=SECRET,
    )
    agent_token = sb._mint_jwt()
    operator_token = sb.mint_operator_token()

    agent_claims = jwt_decode(agent_token, SECRET)
    operator_claims = jwt_decode(operator_token, SECRET)

    assert agent_claims["scope"] == SCOPE_AGENT
    assert operator_claims["scope"] == SCOPE_OPERATOR
    # Same user / session bound into both
    assert agent_claims["sub"] == operator_claims["sub"] == "alice"
    assert agent_claims["sid"] == operator_claims["sid"] == "sess-12345"
