"""DynamicToolFactory — turn :class:`GeneratedToolSpec` into a runnable Tool.

The factory is the consumer of :mod:`orqest.sandbox`. It validates the
implementation, then produces a ``pydantic_ai.Tool`` whose body delegates
to the configured :class:`Sandbox` at invocation time.

Two-phase contract:

1. **Spawn** (``await factory.spawn(spec)``) — validates the implementation
   via the sandbox, returns a :class:`pydantic_ai.Tool`. Raises
   :class:`ValidationError` when the spec fails static checks.
2. **Invoke** (when the agent loop calls the tool) — the spawned tool's
   body hands the args to ``sandbox.execute()``. On success returns the
   raw output; on failure returns a structured error dict so the LLM
   loop sees it as a tool result, not a Python exception.

Bus events (when ``bus`` is supplied):

* ``tool.spawned`` — successful Tool produced.
* ``tool.spawn_failed`` — sandbox.validate rejected the spec.
* ``sandbox.validation_rejected`` — emitted alongside ``tool.spawn_failed``
  for consumers subscribing at the sandbox layer.
* ``tool.invocation_completed`` — successful sandbox.execute() at call time.
* ``tool.invocation_failed`` — failed sandbox.execute() at call time.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from loguru import logger
from pydantic_ai import Tool

from orqest.autonomy.spec import GeneratedToolSpec
from orqest.observability.events import AgentEvent, EventBus
from orqest.sandbox.protocol import Sandbox, ValidationError


class DynamicToolFactory:
    """Spawn :class:`pydantic_ai.Tool` objects from :class:`GeneratedToolSpec`.

    Args:
        sandbox: Required :class:`Sandbox` backend (typically
            :class:`SubprocessSandbox` for production,
            :class:`InProcessSandbox(unsafe=True)` for tests).
        bus: Optional :class:`EventBus` for ``tool.*`` /
            ``sandbox.validation_rejected`` events.
        default_timeout_s: Fallback timeout when a spec doesn't override.
        default_memory_mb: Fallback memory cap when a spec doesn't override.

    """

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        bus: EventBus | None = None,
        default_timeout_s: float = 5.0,
        default_memory_mb: int = 128,
    ) -> None:
        self._sandbox = sandbox
        self._bus = bus
        self._default_timeout_s = default_timeout_s
        self._default_memory_mb = default_memory_mb

    @property
    def sandbox(self) -> Sandbox:
        """The sandbox instance bound at construction time."""
        return self._sandbox

    async def spawn(
        self,
        spec: GeneratedToolSpec,
        *,
        agent_id: str | None = None,
    ) -> Tool:
        """Validate the spec, return a runnable :class:`pydantic_ai.Tool`.

        Args:
            spec: The :class:`GeneratedToolSpec` carrying the implementation
                + parameters + safety knobs.
            agent_id: Optional agent identifier — Tier-2
                :class:`DockerSandbox` routes execution into the agent's
                per-agent subfolder + ``.venv``. Tier-0 / Tier-1 ignore.
                Captured into the runner closure so every invocation of the
                returned ``Tool`` carries the same ``agent_id``.

        Raises:
            ValidationError: When the implementation fails static checks
                (disallowed import, forbidden built-in, syntax error).

        """
        try:
            await self._sandbox.validate(
                spec.implementation, allowed_imports=spec.allowed_imports
            )
        except ValidationError as exc:
            self._emit(
                "sandbox.validation_rejected",
                tool_name=spec.name,
                reason=str(exc),
            )
            self._emit(
                "tool.spawn_failed",
                tool_name=spec.name,
                reason=str(exc),
            )
            raise

        # Bind the spec into the closure so the runner has everything it
        # needs at invocation time.
        timeout_s = spec.timeout_s if spec.timeout_s else self._default_timeout_s
        memory_mb = spec.memory_mb if spec.memory_mb else self._default_memory_mb
        dependencies = list(spec.dependencies) if spec.dependencies else None
        bound_agent_id = agent_id
        sandbox = self._sandbox
        emit = self._emit

        async def _runner(**kwargs: Any) -> Any:
            """Spawned tool body — see DynamicToolFactory.spawn docstring.

            Pydantic-ai's tool loop passes LLM-supplied kwargs here; we
            forward them as the ``args`` dict the sandbox expects.
            """
            result = await sandbox.execute(
                spec.implementation,
                args=dict(kwargs),
                allowed_imports=spec.allowed_imports,
                timeout_s=timeout_s,
                memory_mb=memory_mb,
                agent_id=bound_agent_id,
                dependencies=dependencies,
            )
            if result.success:
                emit(
                    "tool.invocation_completed",
                    tool_name=spec.name,
                    duration_ms=result.duration_ms,
                )
                return result.output
            emit(
                "tool.invocation_failed",
                tool_name=spec.name,
                error=(result.error or "")[:300],
                duration_ms=result.duration_ms,
            )
            # Return a structured error so the LLM agent loop sees it as a
            # tool result (not a Python exception that would crash the loop).
            return {
                "error": result.error or "sandbox execution failed",
                "stage": "sandbox.execute",
                "tool_name": spec.name,
            }

        # Set name + docstring so pydantic-ai surfaces them sensibly.
        _runner.__name__ = spec.name
        _runner.__doc__ = spec.description

        tool = Tool(_runner, name=spec.name, description=spec.description)
        self._emit("tool.spawned", tool_name=spec.name)
        return tool

    def _emit(self, event_type: str, **data: Any) -> None:
        if self._bus is None:
            return
        try:
            event = AgentEvent(
                event_type=event_type,
                agent_name="dynamic_tool_factory",
                data=data,
            )
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                with contextlib.suppress(Exception):
                    asyncio.run(self._bus.emit(event))
                return
            loop.create_task(self._bus.emit(event))
        except Exception as exc:  # noqa: BLE001
            logger.debug("DynamicToolFactory event emit failed: {e}", e=exc)


__all__ = ["DynamicToolFactory"]
