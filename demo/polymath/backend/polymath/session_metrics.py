"""Per-session metrics aggregator — feeds the chat-pane chrome.

The new editorial chrome (per-turn metadata strip + session token-usage
ring) needs two pieces of data the bare event bus doesn't already
supply:

* **Per-turn metadata** — duration, tool count, token usage for the
  just-completed assistant turn, attributed to a stable message id so
  the frontend's ``useChatMetrics`` hook can freeze it onto the
  matching ``UIMessage`` row.
* **Cumulative session usage** — running totals across every turn, so
  the session-header ``Context`` ring can render `total / cap` (and
  the chrome can flag when a long session is creeping toward a context
  limit).

This module owns the in-memory cumulative aggregator. Per-turn data
flows over the event bus as a typed ``chat.turn.completed`` event
(emitted by ``polymath.routers.chat``); ``record_turn`` here updates
the cumulative ledger so ``cumulative_for(sid)`` can be read
synchronously by the GET /sessions/{sid} handler. The aggregator is
deliberately a process-local dict — single-backend localhost demo
discipline; scale-out would back it with Redis or Postgres.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class SessionUsage:
    """Cumulative token + tool + turn counters for one session."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    total_duration_ms: float = 0.0

    def increment(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        tool_calls: int = 0,
        duration_ms: float = 0.0,
    ) -> None:
        """Apply a single turn's deltas in place."""
        self.input_tokens += int(input_tokens)
        self.output_tokens += int(output_tokens)
        self.total_tokens += int(total_tokens)
        self.cache_read_tokens += int(cache_read_tokens)
        self.cache_write_tokens += int(cache_write_tokens)
        self.tool_calls += int(tool_calls)
        self.total_duration_ms += float(duration_ms)
        self.turns += 1


@dataclass
class _MetricsRegistry:
    """Process-local registry: ``session_id`` (str) → :class:`SessionUsage`."""

    _by_session: dict[str, SessionUsage] = field(default_factory=dict)

    def get(self, session_id: str) -> SessionUsage:
        existing = self._by_session.get(session_id)
        if existing is not None:
            return existing
        fresh = SessionUsage()
        self._by_session[session_id] = fresh
        return fresh

    def record_turn(
        self,
        session_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        tool_calls: int,
        duration_ms: float,
    ) -> SessionUsage:
        usage = self.get(session_id)
        usage.increment(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            tool_calls=tool_calls,
            duration_ms=duration_ms,
        )
        return usage

    def reset(self, session_id: str | None = None) -> None:
        """Drop a session's counters (or all sessions when ``None``).

        Test fixtures call this between cases to keep counters
        deterministic across runs.
        """
        if session_id is None:
            self._by_session.clear()
        else:
            self._by_session.pop(session_id, None)


_REGISTRY = _MetricsRegistry()


def record_turn(
    session_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    tool_calls: int,
    duration_ms: float,
) -> SessionUsage:
    """Apply a turn's metrics to the cumulative session ledger.

    Returns the updated :class:`SessionUsage` so the caller (typically
    ``polymath.routers.chat``) can include the post-update snapshot in
    the same ``chat.turn.completed`` event payload.
    """
    return _REGISTRY.record_turn(
        session_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        tool_calls=tool_calls,
        duration_ms=duration_ms,
    )


def cumulative_for(session_id: str) -> dict[str, int | float]:
    """Return the cumulative usage snapshot for *session_id*.

    Always returns a dict (zeros for unseen sessions) so consumer code
    doesn't have to special-case empty sessions.
    """
    return asdict(_REGISTRY.get(session_id))


def reset(session_id: str | None = None) -> None:
    """Test-fixture helper. Drops one session's counters or all."""
    _REGISTRY.reset(session_id)
