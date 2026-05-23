"""Route input to a single step based on rules or LLM classification.

Supports two selection modes:
- Rule-based: evaluate condition callables on each route, first match wins.
- Classifier-driven: an agent or callable returns the route name to execute.

Falls back to a designated fallback step when no route matches.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.orchestration.step import Step, _coerce_step

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class RouterError(Exception):
    """Raised when no route matches and no fallback is configured."""


class Route:
    """A named step with an optional condition for rule-based routing."""

    def __init__(
        self,
        name: str,
        step: Step | BaseAgent | Callable[..., Any],
        *,
        condition: Callable[[Any], bool] | None = None,
    ) -> None:
        """Initialize a route.

        Args:
            name: Identifier used for classifier-based selection.
            step: The StepLike to execute when this route is selected.
            condition: Predicate evaluated in rule-based mode. None means
                this route is only reachable via classifier.

        """
        self.name = name
        self._step: Step = _coerce_step(step)
        self.condition = condition

    @property
    def step(self) -> Step:
        """The coerced Step for this route."""
        return self._step


class Router(Generic[InputT, OutputT]):
    """Select and execute a single route based on input.

    In rule-based mode, routes are evaluated in order and the first whose
    condition returns True is selected. In classifier mode, an agent or
    callable picks the route by name.
    """

    def __init__(
        self,
        routes: list[Route],
        *,
        classifier: BaseAgent | Callable[..., Any] | None = None,
        fallback: Step | BaseAgent | Callable[..., Any] | None = None,
        name: str = "router",
    ) -> None:
        """Initialize the router.

        Args:
            routes: Ordered list of Route objects.
            classifier: Agent or callable that returns a route name.
            fallback: Step executed when no route matches.
            name: Identifier for logging and events.

        Raises:
            ValueError: If routes is empty, or if no classifier is provided
                and none of the routes have conditions.

        """
        if not routes:
            raise ValueError("Router requires at least one route.")
        has_conditions = any(r.condition is not None for r in routes)
        if not has_conditions and classifier is None:
            raise ValueError(
                "Router needs either route conditions or a classifier."
            )
        self._routes = list(routes)
        self._classifier = classifier
        self._fallback: Step | None = _coerce_step(fallback) if fallback else None
        self._name = name
        self._route_map: dict[str, Route] = {r.name: r for r in routes}

    async def run(self, input_data: InputT) -> OutputT:
        """Route input_data to the selected step and return its output.

        Raises:
            RouterError: When no route matches and no fallback exists.

        """
        route_name = await self._select_route(input_data)
        if route_name is not None and route_name in self._route_map:
            return await self._route_map[route_name].step.execute(input_data)
        if self._fallback is not None:
            return await self._fallback.execute(input_data)
        raise RouterError(
            f"No route matched for input and no fallback configured "
            f"(router={self._name!r})."
        )

    async def _select_route(self, input_data: Any) -> str | None:
        """Determine the route name via conditions or classifier."""
        if self._classifier is not None:
            return await self._classify(input_data)
        for route in self._routes:
            if route.condition is not None and route.condition(input_data):
                return route.name
        return None

    async def _classify(self, input_data: Any) -> str:
        """Use the classifier to pick a route name.

        If the classifier is a BaseAgent, it is run with a fresh GlobalState
        and the result is expected to have a ``route`` attribute (duck-typed).
        If it is a callable, it is called directly with input_data and should
        return a route name string.
        """
        if isinstance(self._classifier, BaseAgent):
            state = GlobalState()
            state.add_message("user", str(input_data))
            result = await self._classifier.run(state)
            # Duck-type: look for route/name field on the output model
            if hasattr(result, "route"):
                return str(result.route)
            if hasattr(result, "name"):
                return str(result.name)
            return str(result)
        return await self._classifier(input_data)
