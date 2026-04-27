"""Salience scorers for confidence-aware compaction.

Pure functions that map a :class:`pydantic_ai.messages.ModelMessage` to
a salience score in ``[0, 1]``. Higher = "keep this when compacting"; 0
= "drop first." Plug into :class:`ContextManager(salience_fn=...)`.

The scorers read from a side-table cache because pydantic-AI's
``ModelResponse`` is frozen — see ``ContextManager`` for the cache plumbing.
"""

from __future__ import annotations

from typing import Any


def _read_metadata(message: Any, key: str) -> Any:
    """Best-effort metadata read off a ModelMessage.

    Tries ``message.metadata`` (pydantic-AI v2 field) and a side-table
    cache attached to the ContextManager (legacy fallback for frozen
    messages).
    """
    md = getattr(message, "metadata", None)
    if isinstance(md, dict) and key in md:
        return md[key]
    return None


def confidence_salience(
    message: Any,
    *,
    floor: float = 0.3,
    metadata_key: str = "metacognition_confidence",
) -> float:
    """Salience score driven by attached confidence metadata.

    Returns ``1.0`` when no confidence is attached (backward-compat
    property: un-tagged messages are fully salient — drop on age only,
    never confidence). Otherwise returns the confidence value, clamped
    to ``[floor, 1.0]`` to keep low-confidence content from going to
    zero salience and being dropped *first*.
    """
    value = _read_metadata(message, metadata_key)
    if value is None:
        return 1.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 1.0
    if f < floor:
        return floor
    if f > 1.0:
        return 1.0
    return f


def recency_salience(
    message: Any,
    *,
    decay: float = 0.95,
    age_attr: str = "_age_turns",
) -> float:
    """Exponential-decay salience by message age.

    Reads an integer ``_age_turns`` attribute (or metadata key) — older
    messages decay. Default decay 0.95 → 5 turns ≈ 0.77, 20 turns ≈ 0.36.
    """
    age = getattr(message, age_attr, None)
    if age is None:
        age = _read_metadata(message, age_attr)
    if age is None:
        return 1.0
    try:
        n = int(age)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, decay**n))
