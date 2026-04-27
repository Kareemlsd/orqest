"""Healing primitives — watchdogs, recovery actions, model fallback.

The cognitive substrate's "immune system." Watchdogs subscribe to the
:class:`EventBus`, detect stall / loop / regression patterns, and feed
:class:`RecoveryAction` directives through a :class:`WatchdogHook` into
the existing :class:`HookDecision` pipeline.

See :doc:`/concepts/healing` for the full picture; this module hosts:

* :class:`HealingConfig` — frozen dataclass.
* :class:`Watchdog` Protocol + :class:`Detection` Pydantic model.
* :class:`StallDetector` / :class:`LoopDetector` /
  :class:`RegressionDetector` — concrete watchdogs.
* :class:`RecoveryAction` discriminated union + :class:`WatchdogHook`.
* :func:`resolve_model_with_fallback` + :class:`FallbackModel`.
* :class:`HealingRunner` — wires everything to a :class:`Workbench`'s bus.
"""

from orqest.healing.config import HealingConfig
from orqest.healing.fallback import FallbackModel, resolve_model_with_fallback
from orqest.healing.loop import LoopDetector
from orqest.healing.recovery import (
    AbortRun,
    DiscoverAndRetry,
    EscalateToUser,
    RecoveryAction,
    RetryDifferentModel,
    RetrySameTool,
    WatchdogHook,
    default_policy,
)
from orqest.healing.regression import RegressionDetector
from orqest.healing.runner import HealingRunner
from orqest.healing.stall import StallDetector
from orqest.healing.watchdog import Detection, Watchdog

__all__ = [
    "AbortRun",
    "Detection",
    "DiscoverAndRetry",
    "EscalateToUser",
    "FallbackModel",
    "HealingConfig",
    "HealingRunner",
    "LoopDetector",
    "RecoveryAction",
    "RegressionDetector",
    "RetryDifferentModel",
    "RetrySameTool",
    "StallDetector",
    "Watchdog",
    "WatchdogHook",
    "default_policy",
    "resolve_model_with_fallback",
]
