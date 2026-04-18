"""Retry + enrichment helper for compound tool operations.

Extracted from the repeated pattern found in multi-agent orchestrators where
a compound tool calls a sub-agent, executes side-effects, and on failure
retries with an enriched prompt carrying the previous error.

The helper handles: hook dispatch (before/after/error), retry up to
``max_attempts``, optional note enrichment between attempts, and an
optional retryability filter for non-transient failures.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from orqest.hooks import HookRunner


def _default_enrich(original_note: str, last_error: str) -> str:
    """Prepend the previous error to the note so the sub-agent can course-correct."""
    return (
        f"{original_note}\n\nPREVIOUS ATTEMPT FAILED:\n{last_error}\n"
        "Adjust your approach to avoid this error."
    )


async def run_with_retry(
    operation: Callable[[str], Awaitable[str]],
    *,
    tool_name: str,
    args: dict[str, Any],
    state: Any,
    hooks: HookRunner,
    note: str,
    max_attempts: int = 2,
    enrich_note: Callable[[str, str], str] | None = None,
    is_retryable: Callable[[Exception], bool] | None = None,
) -> str:
    """Run a compound tool operation with retry, enrichment, and hook dispatch.

    Fires ``hooks.run_before`` once at the start and ``hooks.run_after`` once
    with the final result — whether success or exhausted failure. The caller
    does not need to fire hooks itself.

    Args:
        operation: Async callable that takes a (possibly enriched) note and
            returns a serialized result string. Raises on failure.
        tool_name: Name passed to hooks.run_before / run_after for dispatch.
        args: Arguments dict passed to hooks for observability.
        state: Opaque state object passed to hooks (e.g. SessionState).
        hooks: HookRunner that dispatches lifecycle events.
        note: Original note/prompt passed to operation on the first attempt.
        max_attempts: Total number of attempts including the first.
        enrich_note: ``(original_note, last_error_str) -> new_note`` builder
            invoked before every retry. Defaults to ``_default_enrich``.
        is_retryable: ``(exception) -> bool`` predicate. If False, abort
            retrying and emit a failure payload. Default: always retry.

    Returns:
        The operation's successful result string on any attempt, or a
        JSON-serialized failure payload (``{success, error, attempts}``) when
        attempts are exhausted or a non-retryable error occurs.
    """
    await hooks.run_before(tool_name, args, state)
    start = time.monotonic()
    enrich = enrich_note or _default_enrich
    last_error: str | None = None
    attempt = 0

    for attempt in range(max_attempts):
        current_note = note if last_error is None else enrich(note, last_error)
        try:
            result_str = await operation(current_note)
        except Exception as exc:
            last_error = str(exc)
            if is_retryable is not None and not is_retryable(exc):
                logger.warning(
                    "{tool} attempt {n} failed with non-retryable error: {err}",
                    tool=tool_name,
                    n=attempt + 1,
                    err=exc,
                )
                break
            if attempt < max_attempts - 1:
                logger.warning(
                    "{tool} attempt {n} failed, retrying: {err}",
                    tool=tool_name,
                    n=attempt + 1,
                    err=exc,
                )
            continue

        duration_ms = (time.monotonic() - start) * 1000
        await hooks.run_after(tool_name, args, result_str, state, duration_ms)
        return result_str

    result_str = json.dumps({
        "success": False,
        "error": last_error,
        "attempts": attempt + 1,
    })
    duration_ms = (time.monotonic() - start) * 1000
    await hooks.run_after(tool_name, args, result_str, state, duration_ms)
    return result_str
