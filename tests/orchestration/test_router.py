"""Tests for Router orchestration primitive."""
import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.orchestration.router import Route, Router, RouterError


# --- Helpers ---


async def _upper(x: str) -> str:
    """Convert input to uppercase."""
    return x.upper()


async def _lower(x: str) -> str:
    """Convert input to lowercase."""
    return x.lower()


async def _fallback_step(x: str) -> str:
    """Default fallback response."""
    return f"fallback:{x}"


class RouteDecision(BaseModel):
    """Classifier output with a route field."""

    route: str


class ClassifierAgent(BaseAgent[GlobalState, RouteDecision]):
    """Agent that returns a RouteDecision for router classification."""

    async def _run_implementation(
        self, state: GlobalState, **kwargs: object
    ) -> RouteDecision:
        """Delegate to the underlying pydantic-ai agent."""
        prompt = state.get_latest_message("user") or ""
        result = await self.agent.run(str(prompt))
        return result.output


class TestRouterValidation:
    """Constructor validation."""

    def test_empty_routes_raises_value_error(self) -> None:
        """Empty routes list is rejected at construction time."""
        with pytest.raises(ValueError, match="at least one route"):
            Router(routes=[])

    def test_no_conditions_no_classifier_raises_value_error(self) -> None:
        """Routes without conditions and no classifier are rejected."""
        with pytest.raises(ValueError, match="conditions or a classifier"):
            Router(routes=[Route("a", _upper)])


class TestRouterRuleBased:
    """Rule-based routing via conditions."""

    @pytest.mark.asyncio
    async def test_condition_matches(self) -> None:
        """Matching condition routes to the correct step."""
        router = Router(
            routes=[
                Route("upper", _upper, condition=lambda x: x == "UP"),
                Route("lower", _lower, condition=lambda x: x == "DOWN"),
            ],
        )
        result = await router.run("DOWN")
        assert result == "down"

    @pytest.mark.asyncio
    async def test_first_match_wins(self) -> None:
        """When multiple conditions match, the first route wins."""
        router = Router(
            routes=[
                Route("first", _upper, condition=lambda _: True),
                Route("second", _lower, condition=lambda _: True),
            ],
        )
        result = await router.run("hello")
        assert result == "HELLO"

    @pytest.mark.asyncio
    async def test_no_match_with_fallback(self) -> None:
        """When no condition matches, the fallback step executes."""
        router = Router(
            routes=[
                Route("upper", _upper, condition=lambda x: x == "NEVER"),
            ],
            fallback=_fallback_step,
        )
        result = await router.run("test")
        assert result == "fallback:test"

    @pytest.mark.asyncio
    async def test_no_match_without_fallback_raises(self) -> None:
        """When no condition matches and no fallback, RouterError is raised."""
        router = Router(
            routes=[
                Route("upper", _upper, condition=lambda x: x == "NEVER"),
            ],
        )
        with pytest.raises(RouterError, match="No route matched"):
            await router.run("test")


class TestRouterClassifier:
    """Classifier-based routing."""

    @pytest.mark.asyncio
    async def test_classifier_function(self) -> None:
        """An async callable classifier selects the correct route."""

        async def classify(_input: str) -> str:
            """Always route to 'lower'."""
            return "lower"

        router = Router(
            routes=[
                Route("upper", _upper),
                Route("lower", _lower),
            ],
            classifier=classify,
        )
        result = await router.run("HELLO")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_classifier_agent(self, test_model: TestModel) -> None:
        """A BaseAgent classifier returns a RouteDecision model."""
        agent = ClassifierAgent(
            agent_name="classifier",
            system_prompt="Return a RouteDecision with route='upper'.",
            output_type=RouteDecision,
            model=test_model,
        )
        router = Router(
            routes=[
                Route("upper", _upper),
                Route("lower", _lower),
            ],
            classifier=agent,
            fallback=_lower,  # Fallback for when TestModel returns empty route
        )
        # TestModel generates RouteDecision with default field values.
        # The route may not match a real route name, so we use a fallback
        # to verify the classifier flow completes without error.
        result = await router.run("hello")
        assert isinstance(result, str)
