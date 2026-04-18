"""Compound tool pattern: agent decides, system acts.

Combines an agent call with a tool execution and optional state update.
The universal pattern is: agent produces structured output, an executor
runs a tool/action using that output, and state is updated with the result.
Hooks fire before/after the execution step.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from orqest.agents.base_agent import BaseAgent
from orqest.hooks import HookRunner

StateT = TypeVar("StateT")
OutputT = TypeVar("OutputT")


class CompoundTool(Generic[StateT, OutputT]):
    """Combines an agent call with a tool execution and state update.

    Pattern: agent produces structured output, executor runs a tool/action
    using that output, state is updated with the result. Hooks fire
    before/after the execution step.
    """

    def __init__(
        self,
        agent: BaseAgent,
        executor: Callable[[OutputT, StateT], Awaitable[Any]],
        *,
        state_updater: Callable[[StateT, Any], StateT] | None = None,
        hooks: HookRunner | None = None,
        name: str | None = None,
    ) -> None:
        """Initialize the compound tool.

        Args:
            agent: The agent that produces structured output.
            executor: Async callable that acts on (agent_output, state).
            state_updater: Optional callable to update state with the result.
            hooks: HookRunner for before/after/error callbacks.
            name: Tool name for hook dispatch. Defaults to agent.agent_name.

        """
        self.name = name or agent.agent_name
        self._agent = agent
        self._executor = executor
        self._state_updater = state_updater
        self._hooks = hooks or HookRunner()

    async def run(
        self, state: StateT, prompt: str, **kwargs: Any
    ) -> tuple[OutputT, Any]:
        """Execute the compound tool: agent, execute, update state.

        Returns (agent_output, execution_result).
        """
        agent_output = await self._agent.run(state, **kwargs)

        args = {"agent_output": agent_output, "prompt": prompt}
        await self._hooks.run_before(self.name, args, state)

        start = time.monotonic()
        try:
            result = await self._executor(agent_output, state)
            duration_ms = (time.monotonic() - start) * 1000
            await self._hooks.run_after(self.name, args, result, state, duration_ms)
        except Exception as exc:
            await self._hooks.run_error(self.name, args, exc, state)
            raise

        if self._state_updater is not None:
            state = self._state_updater(state, result)

        return agent_output, result
