"""Configuration for the healing subsystem.

Frozen dataclass matching :class:`OrqestConfig` and :class:`MemoryConfig`
patterns. Defaults are conservative — opt-in via :class:`HealingRunner`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HealingConfig:
    """Knobs for healing primitives. Pass explicitly to :class:`HealingRunner`."""

    stall_timeout_s: float = 60.0
    """Detector fires when an open tool call exceeds this duration."""

    loop_threshold_k: int = 3
    """Same ``(tool_name, args_hash)`` more than ``k`` times in the
    sliding window triggers :class:`LoopDetector`."""

    loop_window_n: int = 10
    """Sliding-window size for :class:`LoopDetector` — number of recent
    ``tool.before`` events tracked."""

    regression_window_n: int = 5
    """Number of recent ``metacognition.confidence`` values
    :class:`RegressionDetector` averages over each half (head vs tail)."""

    regression_drop_threshold: float = 0.2
    """Confidence drop (head_mean − tail_mean) required to trigger
    :class:`RegressionDetector`."""

    poll_interval_s: float = 1.0
    """How often :class:`HealingRunner` polls watchdogs."""

    fallback_models: tuple[str, ...] = field(default_factory=tuple)
    """Ordered list of ``provider:model_id`` strings for
    :func:`resolve_model_with_fallback`. Empty disables auto-fallback."""

    enable_stall: bool = True
    enable_loop: bool = True
    enable_regression: bool = False
    """Off by default — needs ``metacognition.confidence`` events
    flowing on the bus."""

    abort_on_unresolved_loop: bool = True
    """When :class:`LoopDetector` fires and policy yields no recovery,
    abort the compound flow rather than continuing the loop."""

    def __post_init__(self) -> None:
        if self.stall_timeout_s <= 0:
            raise ValueError("stall_timeout_s must be > 0")
        if self.loop_threshold_k < 1:
            raise ValueError("loop_threshold_k must be >= 1")
        if self.loop_window_n < self.loop_threshold_k:
            raise ValueError("loop_window_n must be >= loop_threshold_k")
        if self.regression_window_n < 2:
            raise ValueError("regression_window_n must be >= 2")
        if not 0.0 <= self.regression_drop_threshold <= 1.0:
            raise ValueError("regression_drop_threshold must be in [0, 1]")
        if self.poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
