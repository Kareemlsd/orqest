"""Tests for orqest.sandbox.jwt — minimal HS256 JWT helper."""

from __future__ import annotations

import time

import pytest

from orqest.sandbox.jwt import (
    JWTExpiredError,
    JWTMalformedError,
    JWTSignatureError,
    decode,
    encode,
)


SECRET = "0" * 64


# --- Round trip ------------------------------------------------------------


def test_round_trip_simple():
    token = encode({"sub": "alice", "sid": "abc123"}, SECRET)
    claims = decode(token, SECRET, verify_exp=False)
    assert claims == {"sub": "alice", "sid": "abc123"}


def test_round_trip_with_exp():
    token = encode({"sub": "alice", "exp": int(time.time()) + 60}, SECRET)
    claims = decode(token, SECRET)
    assert claims["sub"] == "alice"


def test_secret_can_be_bytes_or_str():
    token_str = encode({"x": 1}, SECRET)
    token_bytes = encode({"x": 1}, SECRET.encode())
    assert token_str == token_bytes


# --- Signature verification ------------------------------------------------


def test_tampered_payload_rejected():
    """Flipping a single character in the payload should fail signature check."""
    token = encode({"sub": "alice"}, SECRET)
    parts = token.split(".")
    # Mutate the payload portion
    bad_payload = parts[1][:-1] + ("X" if parts[1][-1] != "X" else "Y")
    bad_token = ".".join([parts[0], bad_payload, parts[2]])
    with pytest.raises(JWTSignatureError):
        decode(bad_token, SECRET, verify_exp=False)


def test_wrong_secret_rejected():
    token = encode({"sub": "alice"}, SECRET)
    with pytest.raises(JWTSignatureError):
        decode(token, "different-secret-" * 4, verify_exp=False)


def test_alg_none_rejected():
    """Defense against the classic 'alg=none' confusion attack."""
    import base64
    import json

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "attacker"}).encode()
    ).rstrip(b"=").decode()
    token = f"{header}.{payload}."
    with pytest.raises(JWTSignatureError, match="HS256"):
        decode(token, SECRET, verify_exp=False)


# --- Expiry ---------------------------------------------------------------


def test_expired_token_rejected():
    token = encode({"sub": "alice", "exp": int(time.time()) - 60}, SECRET)
    with pytest.raises(JWTExpiredError):
        decode(token, SECRET)


def test_expired_token_accepted_with_verify_exp_false():
    token = encode({"sub": "alice", "exp": int(time.time()) - 60}, SECRET)
    claims = decode(token, SECRET, verify_exp=False)
    assert claims["sub"] == "alice"


def test_expired_within_leeway_accepted():
    token = encode({"sub": "alice", "exp": int(time.time()) - 5}, SECRET)
    # 10s leeway covers the 5s overrun
    claims = decode(token, SECRET, leeway_s=10)
    assert claims["sub"] == "alice"


def test_no_exp_claim_passes_when_verify_exp_true():
    """A token without exp is valid regardless of verify_exp setting."""
    token = encode({"sub": "alice"}, SECRET)
    claims = decode(token, SECRET, verify_exp=True)
    assert claims["sub"] == "alice"


def test_non_integer_exp_rejected():
    token = encode({"sub": "alice", "exp": "tomorrow"}, SECRET)
    with pytest.raises(JWTMalformedError):
        decode(token, SECRET)


# --- Malformed input ------------------------------------------------------


def test_missing_dots_rejected():
    with pytest.raises(JWTMalformedError):
        decode("not.a.valid.jwt.shape", SECRET)


def test_garbage_rejected():
    with pytest.raises(JWTMalformedError):
        decode("garbage", SECRET)


def test_invalid_base64_rejected():
    bad = "header.!!invalid!!.sig"
    with pytest.raises(JWTMalformedError):
        decode(bad, SECRET)
