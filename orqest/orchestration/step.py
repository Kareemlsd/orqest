"""Step protocol and concrete implementations for orchestration.

Defines the Step protocol that all executable units conform to, plus
AgentStep (wraps BaseAgent) and FunctionStep (wraps async callables).
Provides _coerce_step() to auto-wrap raw values into Steps.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState


@runtime_checkable
class Step(Protocol):
    """Minimal interface for an executable pipeline step."""

    @property
    def step_name(self) -> str:
        """Human-readable name for this step."""
        ...

    async def execute(self, input_data: Any) -> Any:
        """Run the step on *input_data* and return a result."""
        ...


def _default_prompt(input_data: Any) -> str:
    """Serialize *input_data* to a prompt string.

    BaseModel instances are serialized as JSON; everything else uses str().
    """
    if isinstance(input_data, BaseModel):
        return json.dumps(input_data.model_dump(), default=str)
    return str(input_data)


class AgentStep:
    """Wraps a BaseAgent as a pipeline Step.

    Creates a fresh GlobalState per invocation so each step execution is
    stateless. Uses a prompt_builder to convert arbitrary input into a string
    prompt for the agent.
    """

    def __init__(
        self,
        agent: BaseAgent,
        *,
        prompt_builder: Callable[[Any], str] | None = None,
    ) -> None:
        """Initialize with a BaseAgent and optional prompt builder.

        Args:
            agent: The BaseAgent to wrap.
            prompt_builder: Converts input_data to a prompt string.
                Defaults to JSON for BaseModel, str() otherwise.

        """
        self._agent = agent
        self._prompt_builder = prompt_builder or _default_prompt

    @property
    def step_name(self) -> str:
        """Return the wrapped agent's name."""
        return self._agent.agent_name

    async def execute(self, input_data: Any) -> Any:
        """Run the agent with a fresh state built from *input_data*."""
        state = GlobalState()
        prompt = self._prompt_builder(input_data)
        state.add_message("user", prompt)
        return await self._agent.run(state)


class FunctionStep:
    """Wraps an async callable as a pipeline Step."""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
    ) -> None:
        """Initialize with an async callable and optional name.

        Args:
            func: The async callable to wrap.
            name: Step name; defaults to the function's __name__.

        """
        self._func = func
        self._name = name or getattr(func, "__name__", "function_step")

    @property
    def step_name(self) -> str:
        """Return the configured or inferred step name."""
        return self._name

    async def execute(self, input_data: Any) -> Any:
        """Call the wrapped function with *input_data*."""
        return await self._func(input_data)


StepLike = Step | BaseAgent | Callable[..., Any]
"""Union type accepted by Pipeline — auto-coerced to Step."""


def _coerce_step(raw: StepLike) -> Step:
    """Convert a StepLike value into a proper Step instance.

    Accepts Step instances (returned as-is), BaseAgent (wrapped in AgentStep),
    and async callables (wrapped in FunctionStep). Raises TypeError otherwise.
    """
    if isinstance(raw, Step):
        return raw
    if isinstance(raw, BaseAgent):
        return AgentStep(raw)
    if callable(raw):
        return FunctionStep(raw)
    msg = f"Cannot coerce {type(raw).__name__} to Step"
    raise TypeError(msg)
