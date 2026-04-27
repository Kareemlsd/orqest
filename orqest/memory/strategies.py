"""Per-kind retrieval strategies for :class:`LocalMemoryStore`.

Three strategies, one dispatch table — chosen at recall time by the
filter's ``memory_type``. Keeps :class:`LocalMemoryStore.recall` from
ballooning into a giant if/else.

* :class:`SemanticStrategy` — embedding cosine when present (TODO),
  FTS5 fallback, LIKE final fallback. ``ORDER BY last_accessed DESC``.
  Identical to the legacy v0.0.1 behavior — chosen by default.
* :class:`EpisodicStrategy` — FTS5 ordered by ``created_at DESC``.
  Honors a ``metadata.session_id`` filter when supplied.
* :class:`ProceduralStrategy` — exact-match on
  ``structured_content.trigger`` (case-insensitive), with an optional
  injected fuzzy-match judge for near-miss queries.

Each strategy executes raw SQL against a passed-in
:class:`aiosqlite.Connection`. The store passes ``fts_available`` so the
strategy can pick FTS5 vs LIKE without re-probing.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

import aiosqlite

from orqest.memory.store import MemoryFilter

# Public type for the optional fuzzy judge: takes the query and a list
# of candidate triggers, returns the indices of triggers it judges
# matching. Index-based so callers don't have to dedupe.
FuzzyJudge = Callable[[str, list[str]], Awaitable[list[int]]]


@runtime_checkable
class RetrievalStrategy(Protocol):
    """One strategy per memory_type. The store dispatches to it."""

    async def recall(
        self,
        db: aiosqlite.Connection,
        query: str,
        *,
        k: int,
        filters: MemoryFilter | None,
        fts_available: bool,
    ) -> list[aiosqlite.Row]:
        ...


def _apply_common_filters(
    filters: MemoryFilter | None,
) -> tuple[list[str], list[Any]]:
    """Build SQL conditions/params for the filter fields shared across
    strategies. Strategy-specific filters (skill_name, skill_min_version)
    are applied by the strategy itself."""
    conditions: list[str] = []
    params: list[Any] = []
    if filters is None:
        return conditions, params
    if filters.memory_type is not None:
        conditions.append("m.memory_type = ?")
        params.append(filters.memory_type)
    if filters.source_agent is not None:
        conditions.append("m.source_agent = ?")
        params.append(filters.source_agent)
    if filters.min_confidence is not None:
        conditions.append("m.confidence >= ?")
        params.append(filters.min_confidence)
    if filters.min_reliability is not None:
        conditions.append("m.reliability_score >= ?")
        params.append(filters.min_reliability)
    return conditions, params


class SemanticStrategy:
    """FTS5 (or LIKE fallback) on ``content``, ordered by recency of access.

    Identical to v0.0.1 behavior. Embedding-cosine path is wired only
    when an ``embedding`` column has data AND the caller has registered
    a vector-similarity SQL fn; otherwise we degrade to FTS5 / LIKE.
    """

    name = "semantic"

    async def recall(
        self,
        db: aiosqlite.Connection,
        query: str,
        *,
        k: int,
        filters: MemoryFilter | None,
        fts_available: bool,
    ) -> list[aiosqlite.Row]:
        conditions, params = _apply_common_filters(filters)

        if fts_available:
            conditions.append(
                "m.id IN (SELECT id FROM memories_fts WHERE content MATCH ?)"
            )
            params.append(f'"{query}"')
        else:
            conditions.append("m.content LIKE ?")
            params.append(f"%{query}%")

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM memories m
            WHERE {where}
            ORDER BY m.last_accessed DESC
            LIMIT ?
        """  # noqa: S608
        params.append(k)
        cursor = await db.execute(sql, params)
        return list(await cursor.fetchall())


class EpisodicStrategy:
    """Time-windowed search ordered by ``created_at DESC``.

    Same content matching as Semantic, but the ordering reflects the
    "what happened" framing of episodic memory. A future extension may
    honor ``filters.metadata.session_id`` for session-scoped recall.
    """

    name = "episodic"

    async def recall(
        self,
        db: aiosqlite.Connection,
        query: str,
        *,
        k: int,
        filters: MemoryFilter | None,
        fts_available: bool,
    ) -> list[aiosqlite.Row]:
        conditions, params = _apply_common_filters(filters)

        if fts_available:
            conditions.append(
                "m.id IN (SELECT id FROM memories_fts WHERE content MATCH ?)"
            )
            params.append(f'"{query}"')
        else:
            conditions.append("m.content LIKE ?")
            params.append(f"%{query}%")

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM memories m
            WHERE {where}
            ORDER BY m.created_at DESC
            LIMIT ?
        """  # noqa: S608
        params.append(k)
        cursor = await db.execute(sql, params)
        return list(await cursor.fetchall())


class ProceduralStrategy:
    """Trigger-match retrieval for skills.

    Algorithm:
        1. Lower-case the query.
        2. SQL: select procedural rows whose
           ``structured_content -> '$.trigger'`` (lower-cased) equals the
           query OR contains the query as a substring.
        3. Honor ``filters.skill_name`` (exact match on
           ``structured_content -> '$.name'``) and
           ``filters.skill_min_version`` (``version`` numeric compare).
        4. Order by ``reliability_score DESC, version DESC, last_accessed DESC``.
        5. If exact-match returns rows, return up to ``k``.
        6. Else if ``fuzzy_judge`` is configured, ask it to pick from
           the top 20 candidate triggers and return judged matches.
        7. Else return ``[]``.

    The fuzzy judge is **injected, not built-in** — Orqest core stays
    LLM-judge-neutral; the consumer wires one if desired.
    """

    name = "procedural"

    def __init__(self, fuzzy_judge: FuzzyJudge | None = None) -> None:
        self._judge = fuzzy_judge

    async def recall(
        self,
        db: aiosqlite.Connection,
        query: str,
        *,
        k: int,
        filters: MemoryFilter | None,
        fts_available: bool,
    ) -> list[aiosqlite.Row]:
        conditions, params = _apply_common_filters(filters)
        # Always require procedural type for this strategy.
        if filters is None or filters.memory_type is None:
            conditions.append("m.memory_type = 'procedural'")
        # structured_content must be present.
        conditions.append("m.structured_content IS NOT NULL")

        # skill_name / skill_min_version
        if filters is not None and filters.skill_name is not None:
            conditions.append(
                "json_extract(m.structured_content, '$.name') = ?"
            )
            params.append(filters.skill_name)
        if filters is not None and filters.skill_min_version is not None:
            conditions.append(
                "CAST(json_extract(m.structured_content, '$.version') AS INTEGER) >= ?"
            )
            params.append(filters.skill_min_version)

        # Trigger match: equality OR substring (case-insensitive).
        q_lower = query.lower()
        conditions.append(
            "("
            "lower(json_extract(m.structured_content, '$.trigger')) = ? "
            "OR lower(json_extract(m.structured_content, '$.trigger')) LIKE ?"
            ")"
        )
        params.append(q_lower)
        params.append(f"%{q_lower}%")

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM memories m
            WHERE {where}
            ORDER BY m.reliability_score DESC,
                     CAST(json_extract(m.structured_content, '$.version') AS INTEGER) DESC,
                     m.last_accessed DESC
            LIMIT ?
        """  # noqa: S608
        params.append(k)
        cursor = await db.execute(sql, params)
        rows = list(await cursor.fetchall())

        if rows or self._judge is None:
            return rows

        # Fuzzy fallback: pull up to 20 procedural triggers, ask the
        # judge to pick matches, return those.
        candidate_sql = """
            SELECT * FROM memories m
            WHERE m.memory_type = 'procedural'
              AND m.structured_content IS NOT NULL
            ORDER BY m.last_accessed DESC
            LIMIT 20
        """
        cursor = await db.execute(candidate_sql)
        candidates = list(await cursor.fetchall())
        if not candidates:
            return []

        triggers: list[str] = []
        for row in candidates:
            try:
                payload = json.loads(row["structured_content"])
                triggers.append(str(payload.get("trigger", "")))
            except Exception:
                triggers.append("")
        chosen_idx = await self._judge(query, triggers)
        return [candidates[i] for i in chosen_idx if 0 <= i < len(candidates)][:k]


def default_strategy_table() -> dict[str, RetrievalStrategy]:
    """The default per-kind retrieval table used by :class:`LocalMemoryStore`."""
    return {
        "semantic": SemanticStrategy(),
        "episodic": EpisodicStrategy(),
        "procedural": ProceduralStrategy(),
    }
