"""``MetacognitionConfig`` — orchestration policy for confidence-driven behaviour.

Frozen dataclass matching :class:`OrqestConfig` and :class:`MemoryConfig`
patterns. Used by :class:`MetaOrchestrator` to drive re-decomposition
on confidence drop. Defaults are conservative.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetacognitionConfig:
    """Policy knobs for confidence-driven orchestration."""

    redecompose_threshold: float = 0.5
    """Below this confidence, :class:`MetaOrchestrator` re-decomposes
    the remaining subtasks. Must be in ``[0, 1]``."""

    max_redecompositions: int = 2
    """Hard cap on re-decompositions per ``solve()`` call. Prevents
    runaway cost when a sub-task can't recover."""

    confidence_floor: float = 0.0
    """Below this floor, downstream consumers should treat the output
    as if ``capability_boundary=True``."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.redecompose_threshold <= 1.0:
            raise ValueError("redecompose_threshold must be in [0, 1]")
        if not 0.0 <= self.confidence_floor <= 1.0:
            raise ValueError("confidence_floor must be in [0, 1]")
        if self.max_redecompositions < 0:
            raise ValueError("max_redecompositions must be >= 0")
