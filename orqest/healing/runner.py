"""HealingRunner — wires watchdogs to a bus and runs a poll loop.

Lifecycle:

    runner = HealingRunner(config, bus=workbench.event_bus, api_key=cfg.llm_api_key)
    async with runner:
        hooks = HookRunner([runner.hook, EventBusPublishHook(bus)])
        ...

Or for tests / non-async-context wiring:

    await runner.start()
    try:
        ...
    finally:
        await runner.stop()
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from pydantic_ai.models import Model

from orqest.healing.config import HealingConfig
from orqest.healing.fallback import ApiKeyArg, resolve_model_with_fallback
from orqest.healing.loop import LoopDetector
from orqest.healing.recovery import WatchdogHook
from orqest.healing.regression import RegressionDetector
from orqest.healing.stall import StallDetector
from orqest.healing.watchdog import Watchdog
from orqest.observability.events import AgentEvent, EventBus


class HealingRunner:
    """Owns the healing lifecycle for a single :class:`EventBus`.

    Constructs watchdogs from :class:`HealingConfig`, subscribes them
    to the bus, and runs a poll loop that:

    * calls each watchdog's :meth:`signal` periodically (so detectors
      that compute on demand, like :class:`StallDetector`, fire);
    * emits ``healing.detection`` events for each Detection produced.

    The :class:`WatchdogHook` is exposed as ``runner.hook`` for the
    consumer to register on a :class:`HookRunner`.

    The fallback :class:`Model` (if configured) is exposed as
    ``runner.model``; pass it to :class:`BaseAgent`.
    """

    def __init__(
        self,
        config: HealingConfig,
        *,
        bus: EventBus,
        api_key: ApiKeyArg | None = None,
        watchdogs: list[Watchdog] | None = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._watchdogs: list[Watchdog] = list(watchdogs) if watchdogs else []
        if not self._watchdogs:
            if config.enable_stall:
                self._watchdogs.append(
                    StallDetector(timeout_s=config.stall_timeout_s)
                )
            if config.enable_loop:
                self._watchdogs.append(
                    LoopDetector(
                        threshold_k=config.loop_threshold_k,
                        window_n=config.loop_window_n,
                    )
                )
            if config.enable_regression:
                self._watchdogs.append(
                    RegressionDetector(
                        window_n=config.regression_window_n,
                        drop_threshold=config.regression_drop_threshold,
                    )
                )
        for wd in self._watchdogs:
            wd.subscribe(self._bus)

        self.hook = WatchdogHook(self._watchdogs, bus=self._bus)
        self._poll_task: asyncio.Task[None] | None = None

        self._fallback_model: Model | None = None
        if config.fallback_models and api_key is not None:
            try:
                self._fallback_model = resolve_model_with_fallback(
                    list(config.fallback_models),
                    api_key=api_key,
                    bus=self._bus,
                )
            except Exception as exc:
                logger.warning(
                    "Could not configure fallback model chain {m!r}: {e}",
                    m=config.fallback_models,
                    e=exc,
                )

    @property
    def model(self) -> Model | None:
        """The fallback-aware :class:`Model`, or ``None`` if not configured."""
        return self._fallback_model

    @property
    def watchdogs(self) -> list[Watchdog]:
        """The active watchdog list (for inspection / tests)."""
        return list(self._watchdogs)

    async def __aenter__(self) -> HealingRunner:
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    async def start(self) -> None:
        if self._poll_task is not None:
            return

        async def _poll() -> None:
            while True:
                try:
                    for wd in self._watchdogs:
                        try:
                            det = await wd.signal()
                        except Exception:
                            logger.warning(
                                "Watchdog {n} crashed during signal()",
                                n=getattr(wd, "name", type(wd).__name__),
                            )
                            continue
                        if det is None:
                            continue
                        await self._bus.emit(
                            AgentEvent(
                                event_type="healing.detection",
                                agent_name=det.detector,
                                data={"detection": det.model_dump()},
                            )
                        )
                except Exception:
                    logger.warning("Healing poll iteration crashed; continuing")
                await asyncio.sleep(self._config.poll_interval_s)

        self._poll_task = asyncio.create_task(_poll())

    async def stop(self) -> None:
        if self._poll_task is None:
            return
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        self._poll_task = None
