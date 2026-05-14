"""Compound tool pattern: agent decides, system acts.

Combines an agent call with a tool execution and optional state update.
The universal pattern is: agent produces structured output, an executor
runs a tool/action using that output, and state is updated with the result.
Hooks fire before/after the execution step and may issue
:class:`HookDecision` directives to skip, redirect, or abort the call.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from orqest.agents.base_agent import BaseAgent
from orqest.hooks import (
    HookAbortError,
    HookRunner,
    Redirect,
    Skip,
)

StateT = TypeVar("StateT")
OutputT = TypeVar("OutputT")


class CompoundTool(Generic[StateT, OutputT]):
    """Combines an agent call with a tool execution and state update.

    Pattern: agent produces structured output, executor runs a tool/action
    using that output, state is updated with the result. Hooks fire
    before/after the execution step and can influence flow via
    :class:`HookDecision`.
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
        """Execute the compound tool: agent, decide, execute, update state.

        Returns ``(agent_output, execution_result)``. Honors
        :class:`Skip` (returns ``stub_result`` in place of executor),
        :class:`Redirect` (mutates args/name; bounded one re-execution
        on ``after_tool`` redirect), and :class:`Abort` (raises
        :class:`HookAbortError` to the caller).
        """
        agent_output = await self._agent.run(state, **kwargs)

        args = {"agent_output": agent_output, "prompt": prompt}
        effective_name = self.name
        effective_args: dict[str, Any] = args

        before_decision = await self._hooks.run_before(
            effective_name, effective_args, state
        )

        if isinstance(before_decision, Skip):
            result = before_decision.stub_result
            await self._hooks.run_after(
                effective_name, effective_args, result, state, 0.0
            )
            if self._state_updater is not None:
                state = self._state_updater(state, result)
            return agent_output, result

        if isinstance(before_decision, Redirect):
            if before_decision.new_args is not None:
                effective_args = {**effective_args, **before_decision.new_args}
            if before_decision.new_tool is not None:
                effective_name = before_decision.new_tool

        start = time.monotonic()
        try:
            result = await self._executor(agent_output, state)
            duration_ms = (time.monotonic() - start) * 1000
        except HookAbortError:
            raise
        except Exception as exc:
            error_decision = await self._hooks.run_error(
                effective_name, effective_args, exc, state
            )
            if not isinstance(error_decision, Redirect):
                raise
            # on_error Redirect → bounded single retry of the executor
            # (e.g. DiscoveryHook registered the missing tool). A second
            # failure is not retried — it propagates.
            if error_decision.new_args is not None:
                effective_args = {**effective_args, **error_decision.new_args}
            if error_decision.new_tool is not None:
                effective_name = error_decision.new_tool
            start = time.monotonic()
            result = await self._executor(agent_output, state)
            duration_ms = (time.monotonic() - start) * 1000

        after_decision = await self._hooks.run_after(
            effective_name, effective_args, result, state, duration_ms
        )

        # Bounded one re-execution on after_tool redirect.
        if isinstance(after_decision, Redirect):
            if after_decision.new_args is not None:
                effective_args = {**effective_args, **after_decision.new_args}
            start = time.monotonic()
            try:
                result = await self._executor(agent_output, state)
                duration_ms = (time.monotonic() - start) * 1000
                # Final after_tool — any further Redirect from this call is
                # ignored (logged inside HookRunner) to bound the loop.
                await self._hooks.run_after(
                    effective_name, effective_args, result, state, duration_ms
                )
            except HookAbortError:
                raise
            except Exception as exc:
                await self._hooks.run_error(
                    effective_name, effective_args, exc, state
                )
                raise

        if self._state_updater is not None:
            state = self._state_updater(state, result)

        return agent_output, result
