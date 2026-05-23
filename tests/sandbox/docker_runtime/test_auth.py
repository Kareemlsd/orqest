"""Tests for orqest.sandbox.docker_runtime.auth.SessionAuthMiddleware."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from orqest.sandbox.docker_runtime.auth import (
    SessionAuthError,
    SessionAuthMiddleware,
)
from orqest.sandbox.jwt import encode as jwt_encode

SECRET = "0" * 64
USER = "alice"
SID = "session-abc123"


def _valid_token(*, sub: str = USER, sid: str = SID, exp_offset: int = 60):
    return jwt_encode(
        {"sub": sub, "sid": sid, "exp": int(time.time()) + exp_offset}, SECRET
    )


# --- Construction validation ----------------------------------------------


class TestConstruction:
    def test_secret_required(self):
        with pytest.raises(ValueError, match="HMAC secret"):
            SessionAuthMiddleware(
                secret="", expected_user_id="x", expected_session_id="y"
            )

    def test_user_id_required(self):
        with pytest.raises(ValueError, match="expected_user_id"):
            SessionAuthMiddleware(
                secret="x", expected_user_id="", expected_session_id="y"
            )

    def test_session_id_required(self):
        with pytest.raises(ValueError, match="expected_session_id"):
            SessionAuthMiddleware(
                secret="x", expected_user_id="x", expected_session_id=""
            )

    def test_from_env_reads_required_vars(self, monkeypatch):
        monkeypatch.setenv("ORQEST_HMAC_SECRET", SECRET)
        monkeypatch.setenv("ORQEST_USER_ID", "bob")
        monkeypatch.setenv("ORQEST_SESSION_ID", "session-xyz")
        monkeypatch.delenv("ORQEST_ALLOWED_ORIGINS", raising=False)
        mw = SessionAuthMiddleware.from_env()
        assert mw._expected_user_id == "bob"
        assert mw._expected_session_id == "session-xyz"
        # ORQEST_ALLOWED_ORIGINS unset → secure default (localhost only).
        assert mw._allowed_origins == {"http://127.0.0.1", "http://localhost"}

    def test_from_env_explicit_empty_disables_origin_check(self, monkeypatch):
        """Operators who genuinely don't want an Origin check can still
        disable by setting the env var to an empty string."""
        monkeypatch.setenv("ORQEST_HMAC_SECRET", SECRET)
        monkeypatch.setenv("ORQEST_USER_ID", "bob")
        monkeypatch.setenv("ORQEST_SESSION_ID", "session-xyz")
        monkeypatch.setenv("ORQEST_ALLOWED_ORIGINS", "")
        mw = SessionAuthMiddleware.from_env()
        assert mw._allowed_origins == set()

    def test_from_env_explicit_origins_override_default(self, monkeypatch):
        monkeypatch.setenv("ORQEST_HMAC_SECRET", SECRET)
        monkeypatch.setenv("ORQEST_USER_ID", "bob")
        monkeypatch.setenv("ORQEST_SESSION_ID", "session-xyz")
        monkeypatch.setenv(
            "ORQEST_ALLOWED_ORIGINS",
            "https://example.com,https://api.example.com",
        )
        mw = SessionAuthMiddleware.from_env()
        assert mw._allowed_origins == {
            "https://example.com",
            "https://api.example.com",
        }


# --- _verify_request — the actual auth logic ----------------------------


@pytest.fixture
def mw():
    return SessionAuthMiddleware(
        secret=SECRET,
        expected_user_id=USER,
        expected_session_id=SID,
    )


def test_valid_token_passes(mw):
    token = _valid_token()
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={"authorization": f"Bearer {token}"},
    ):
        # Should not raise
        mw._verify_request(stage="test")


def test_missing_bearer_rejected(mw):
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={},
    ), pytest.raises(SessionAuthError, match="missing bearer token"):
        mw._verify_request(stage="test")


def test_empty_bearer_rejected(mw):
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={"authorization": "Bearer "},
    ), pytest.raises(SessionAuthError, match="empty bearer token"):
        mw._verify_request(stage="test")


def test_tampered_token_rejected(mw):
    token = _valid_token()
    bad = token[:-2] + "XX"
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={"authorization": f"Bearer {bad}"},
    ), pytest.raises(SessionAuthError, match="invalid bearer token"):
        mw._verify_request(stage="test")


def test_expired_token_rejected(mw):
    token = _valid_token(exp_offset=-60)  # expired 60s ago
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={"authorization": f"Bearer {token}"},
    ), pytest.raises(SessionAuthError, match="invalid bearer token"):
        mw._verify_request(stage="test")


def test_wrong_user_rejected(mw):
    token = _valid_token(sub="attacker")
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={"authorization": f"Bearer {token}"},
    ), pytest.raises(SessionAuthError, match="user_id mismatch"):
        mw._verify_request(stage="test")


def test_wrong_session_rejected(mw):
    token = _valid_token(sid="other-session")
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={"authorization": f"Bearer {token}"},
    ), pytest.raises(SessionAuthError, match="session_id mismatch"):
        mw._verify_request(stage="test")


def test_origin_not_in_allowlist_rejected():
    mw = SessionAuthMiddleware(
        secret=SECRET,
        expected_user_id=USER,
        expected_session_id=SID,
        allowed_origins={"http://localhost:3000"},
    )
    token = _valid_token()
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={
            "authorization": f"Bearer {token}",
            "origin": "http://evil.example",
        },
    ), pytest.raises(SessionAuthError, match="origin not allowed"):
        mw._verify_request(stage="test")


def test_origin_in_allowlist_passes():
    mw = SessionAuthMiddleware(
        secret=SECRET,
        expected_user_id=USER,
        expected_session_id=SID,
        allowed_origins={"http://localhost:3000"},
    )
    token = _valid_token()
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={
            "authorization": f"Bearer {token}",
            "origin": "http://localhost:3000",
        },
    ):
        mw._verify_request(stage="test")  # no raise


def test_no_origin_header_with_allowlist_passes():
    """Origin is optional — only check it when present."""
    mw = SessionAuthMiddleware(
        secret=SECRET,
        expected_user_id=USER,
        expected_session_id=SID,
        allowed_origins={"http://localhost:3000"},
    )
    token = _valid_token()
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        return_value={"authorization": f"Bearer {token}"},
    ):
        mw._verify_request(stage="test")  # no raise


def test_outside_http_context_fails_closed(mw):
    """When not inside an HTTP request (e.g. stdio test), reject."""
    with patch(
        "fastmcp.server.dependencies.get_http_headers",
        side_effect=RuntimeError("not in HTTP context"),
    ), pytest.raises(SessionAuthError, match="auth context unavailable"):
        mw._verify_request(stage="test")
