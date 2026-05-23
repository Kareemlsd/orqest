"""Minimal HS256 JWT helper for Sandbox transport authentication.

A JWT here is `<base64url(header)>.<base64url(claims)>.<base64url(signature)>`
where signature = HMAC-SHA256(secret, header_b64 + '.' + claims_b64).

Why a hand-rolled implementation rather than ``pyjwt``:

* Used in exactly one place (Tier-2 sandbox transport auth). One dependency
  for one feature is the wrong tradeoff.
* The full ``pyjwt`` surface (multiple algorithms, JWKS, audience/issuer
  validation, PEM handling) is way more than we need.
* Constant-time signature comparison and HS256 are both ~20 lines.

What this DOES NOT do (deliberately):

* No RS256 / ES256 / EdDSA — only symmetric HS256.
* No JWKS / key rotation — single shared HMAC secret.
* No ``iss`` / ``aud`` validation — we check ``sub`` (user_id), ``sid``
  (session_id), and ``exp`` only.
* No ``nbf`` (not-before) — irrelevant for our use case.

The narrow scope is the safety: less surface means less to misuse.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class JWTError(Exception):
    """Raised when JWT decode / verification fails.

    Subclasses surface specific failure modes so callers can branch on
    them (e.g., distinguishing "expired" from "tampered" for telemetry).
    """


class JWTSignatureError(JWTError):
    """Signature didn't match — either tampered token or wrong secret."""


class JWTExpiredError(JWTError):
    """``exp`` claim is in the past."""


class JWTMalformedError(JWTError):
    """Token isn't shaped like a JWT (missing dots, invalid base64, bad JSON)."""


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 with padding stripped (RFC 7515 §2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Reverse of :func:`_b64url_encode`. Re-adds padding."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode(claims: dict, secret: str | bytes) -> str:
    """Encode *claims* as an HS256-signed JWT.

    The ``exp`` claim, if present, is preserved verbatim — callers compute
    expiry themselves (e.g., ``int(time.time()) + 3600``).

    Args:
        claims: Dict of JSON-serializable claims. Typically
            ``{"sub": user_id, "sid": session_id, "exp": int(time.time()+N)}``.
        secret: HMAC secret. Anything ≥ 32 bytes is fine; 64+ is recommended.

    Returns:
        The compact-form JWT string.

    """
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    header = {"alg": "HS256", "typ": "JWT"}
    h_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    c_b64 = _b64url_encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{h_b64}.{c_b64}".encode("ascii")
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    s_b64 = _b64url_encode(sig)
    return f"{h_b64}.{c_b64}.{s_b64}"


def decode(
    token: str,
    secret: str | bytes,
    *,
    verify_exp: bool = True,
    leeway_s: int = 0,
) -> dict:
    """Decode + verify an HS256 JWT; return the claims dict.

    Raises:
        JWTMalformedError: Bad shape / invalid base64 / bad JSON.
        JWTSignatureError: HMAC didn't match (tampered or wrong secret).
        JWTExpiredError: ``exp`` claim is past current time (minus leeway).

    Args:
        token: The compact-form JWT.
        secret: Same secret used to encode.
        verify_exp: When True (default), reject expired tokens. Set False
            only for offline introspection (debugging).
        leeway_s: Optional grace period in seconds applied to ``exp``
            (handles minor clock skew between issuer and verifier).

    """
    if isinstance(secret, str):
        secret = secret.encode("utf-8")

    parts = token.split(".")
    if len(parts) != 3:
        raise JWTMalformedError(f"expected 3 dot-separated parts, got {len(parts)}")
    h_b64, c_b64, s_b64 = parts

    # Verify header alg before doing anything else
    try:
        header = json.loads(_b64url_decode(h_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise JWTMalformedError(f"header decode failed: {exc}") from exc
    if header.get("alg") != "HS256":
        # Block alg=none and any non-HS256 algorithm (alg-confusion defense)
        raise JWTSignatureError(f"unsupported alg {header.get('alg')!r}; only HS256 accepted")

    # Recompute signature in constant time
    signing_input = f"{h_b64}.{c_b64}".encode("ascii")
    expected = hmac.new(secret, signing_input, hashlib.sha256).digest()
    try:
        provided = _b64url_decode(s_b64)
    except ValueError as exc:
        raise JWTMalformedError(f"signature decode failed: {exc}") from exc
    if not hmac.compare_digest(expected, provided):
        raise JWTSignatureError("signature mismatch")

    # Decode claims
    try:
        claims = json.loads(_b64url_decode(c_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise JWTMalformedError(f"claims decode failed: {exc}") from exc

    # Optional exp check
    if verify_exp:
        exp = claims.get("exp")
        if exp is not None:
            try:
                exp_int = int(exp)
            except (TypeError, ValueError) as exc:
                raise JWTMalformedError(
                    f"exp claim not an integer: {exp!r}"
                ) from exc
            if int(time.time()) > exp_int + leeway_s:
                raise JWTExpiredError(
                    f"exp {exp_int} < now {int(time.time())} (leeway {leeway_s}s)"
                )

    return claims


__all__ = [
    "JWTError",
    "JWTExpiredError",
    "JWTMalformedError",
    "JWTSignatureError",
    "decode",
    "encode",
]
