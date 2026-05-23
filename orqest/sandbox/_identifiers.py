"""Strict identifier validation for sandbox user / session / agent IDs.

These identifiers feed directly into filesystem paths and Docker volume
names (e.g. ``/workspace/<session_id>/<agent_id>/venv/``,
``orqest-user-<user_id>``). Without validation, an LLM-emitted
``agent_id="../../tmp/leak"`` traverses out of the per-agent workspace
into shared writable areas; even though the container's read-only root
+ ``cap-drop=ALL`` bound the damage, workspace pollution and venv
shadowing are real risks.

Validation is a deliberate, narrow allowlist — start with an alphanum,
follow with alphanum / underscore / dash, max 64 chars. UUIDs, slugs,
and human-friendly names all pass; everything else (path separators,
spaces, dots, anything Unicode-fancy) is rejected.
"""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def is_valid_identifier(name: str) -> bool:
    """Return ``True`` iff *name* matches the sandbox identifier grammar."""
    if not isinstance(name, str):
        return False
    return bool(_IDENTIFIER_RE.match(name))


def check_identifier(name: str, *, kind: str) -> None:
    """Raise :class:`ValueError` if *name* is not a valid identifier.

    *kind* is included in the error message so the offending field is
    obvious in tracebacks (``"agent_id"``, ``"session_id"``, ``"user_id"``).
    """
    if not is_valid_identifier(name):
        raise ValueError(
            f"invalid {kind} {name!r}: must match {_IDENTIFIER_RE.pattern} "
            f"(alphanumeric start, then alphanumeric/_/-/, max 64 chars)"
        )


__all__ = ["check_identifier", "is_valid_identifier"]
