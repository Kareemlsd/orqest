"""Integration tests — metacognition wired into BaseAgent / RefinementLoop /
SubAgentTool / ContextManager / MetaOrchestrator."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.context_manager import ContextManager
from orqest.agents.state import GlobalState
from orqest.compound.sub_agent_tool import EvalResult as SubEvalResult
from orqest.compound.sub_agent_tool import SubAgentTool
from orqest.orchestration.loop import EvalResult
from orqest.metacognition import (
    EnrichedOutput,
    StructuredOutputProtocol,
    confidence_salience,
)
from orqest.orchestration.loop import RefinementLoop


class _Out(BaseModel):
    answer: str
    self_confidence: float | None = None
    uncertain_about: list[str] = []
    outside_my_capability: bool = False


class _StubAgent(BaseAgent):
    """Minimal BaseAgent subclass — bypasses pydantic-AI."""

    def __init__(self, fixed_output: _Out, **kwargs):
        # We don't need the full BaseAgent init machinery for unit tests;
        # just stash what we need.
        self._fixed = fixed_output
        self._confidence_protocol = kwargs.get("confidence_protocol")
        self.agent_name = "stub"

    async def _run_implementation(self, state, **kwargs) -> _Out:
        return self._fixed


# ---- BaseAgent.run_enriched ------------------------------------------


@pytest.mark.asyncio
async def test_run_enriched_no_protocol_returns_bare_enrichment():
    agent = _StubAgent(_Out(answer="42", self_confidence=0.9))
    enriched = await agent.run_enriched(GlobalState())
    assert enriched.output.answer == "42"
    assert enriched.confidence is None  # No protocol → no confidence read.
    assert enriched.protocol_name is None


@pytest.mark.asyncio
async def test_run_enriched_with_structured_protocol_lifts_confidence():
    agent = _StubAgent(
        _Out(answer="42", self_confidence=0.9, uncertain_about=["x"]),
        confidence_protocol=StructuredOutputProtocol(),
    )
    enriched = await agent.run_enriched(GlobalState())
    assert enriched.confidence == 0.9
    assert enriched.uncertainty_targets == ["x"]
    assert enriched.protocol_name == "structured"


@pytest.mark.asyncio
async def test_run_enriched_per_call_protocol_overrides_default():
    agent = _StubAgent(
        _Out(answer="42", self_confidence=0.5),
        confidence_protocol=None,
    )
    enriched = await agent.run_enriched(
        GlobalState(),
        confidence_protocol=StructuredOutputProtocol(),
    )
    assert enriched.confidence == 0.5


@pytest.mark.asyncio
async def test_run_enriched_protocol_failure_is_logged_not_raised():
    class _BrokenProtocol:
        name = "broken"

        async def enrich(self, agent, state, output, **kw):
            raise RuntimeError("kaboom")

    agent = _StubAgent(
        _Out(answer="42"),
        confidence_protocol=_BrokenProtocol(),
    )
    enriched = await agent.run_enriched(GlobalState())
    assert enriched.confidence is None
    assert "protocol_error" in enriched.metadata


@pytest.mark.asyncio
async def test_run_unaffected_by_confidence_protocol():
    """The bare run() path is byte-identical to legacy."""
    agent = _StubAgent(
        _Out(answer="42", self_confidence=0.9),
        confidence_protocol=StructuredOutputProtocol(),
    )
    output = await agent.run(GlobalState())
    assert isinstance(output, _Out)
    assert output.answer == "42"


# ---- RefinementLoop integration --------------------------------------


@pytest.mark.asyncio
async def test_refinement_loop_confidence_threshold_exit():
    """When score >= confidence_threshold, exit with reason 'confident'."""
    iterations: list[int] = []

    async def step(input_):
        iterations.append(1)
        return {"answer": "x"}

    async def evaluator(output):
        # Always return below-passing but high-score.
        return EvalResult(passed=False, feedback="", score=0.95)

    loop = RefinementLoop(
        step=step,
        evaluator=evaluator,
        state_updater=lambda *a, **k: a[0],
        max_iterations=5,
        confidence_threshold=0.9,
    )
    result = await loop.run("init")
    assert result.exit_reason == "confident"
    assert result.iterations == 1
    assert len(iterations) == 1


@pytest.mark.asyncio
async def test_refinement_loop_confidence_threshold_below_bar_continues():
    iterations = [0]

    async def step(input_):
        iterations[0] += 1
        return {"a": iterations[0]}

    async def evaluator(output):
        return EvalResult(passed=False, feedback="", score=0.3)

    loop = RefinementLoop(
        step=step,
        evaluator=evaluator,
        state_updater=lambda inp, out, ev: out,
        max_iterations=3,
        confidence_threshold=0.9,
    )
    result = await loop.run("init")
    assert result.exit_reason == "max_iterations"
    assert result.iterations == 3


@pytest.mark.asyncio
async def test_refinement_loop_agent_self_eval_drives_score():
    """When agent_self_eval is set, score = enriched.confidence."""
    iterations = [0]

    async def step(input_):
        iterations[0] += 1
        return _Out(answer=f"v{iterations[0]}", self_confidence=0.95)

    rater = _StubAgent(
        _Out(answer="rating", self_confidence=0.95),
        confidence_protocol=StructuredOutputProtocol(),
    )

    loop = RefinementLoop(
        step=step,
        evaluator=lambda o: EvalResult(passed=False, feedback="", score=None),
        state_updater=lambda inp, out, ev: out,
        max_iterations=5,
        confidence_threshold=0.9,
        agent_self_eval=rater,
    )
    result = await loop.run("init")
    assert result.exit_reason == "confident"


def test_refinement_loop_self_eval_requires_threshold():
    rater = _StubAgent(_Out(answer="x"))
    with pytest.raises(ValueError):
        RefinementLoop(
            step=lambda x: {},
            evaluator=lambda o: EvalResult(passed=False, feedback=""),
            state_updater=lambda *a, **k: a[0],
            max_iterations=3,
            agent_self_eval=rater,
        )


# ---- SubAgentTool integration ----------------------------------------


@pytest.mark.asyncio
async def test_sub_agent_tool_use_enriched_lifts_confidence():
    agent = _StubAgent(
        _Out(answer="42", self_confidence=0.7, uncertain_about=["x"]),
        confidence_protocol=StructuredOutputProtocol(),
    )

    state = {"results": []}

    async def executor(output, state):
        return f"executed:{output.answer}"

    def state_updater(result, state):
        state["results"].append(result)

    tool = SubAgentTool(agent, executor, state_updater)
    result = await tool.run(state, "do it", use_enriched=True)
    assert result.confidence == 0.7
    assert result.uncertainty_targets == ["x"]
    assert state["results"] == ["executed:42"]


@pytest.mark.asyncio
async def test_sub_agent_tool_default_use_enriched_false():
    """When use_enriched=False (default), confidence stays None."""
    agent = _StubAgent(
        _Out(answer="42", self_confidence=0.7),
        confidence_protocol=StructuredOutputProtocol(),
    )

    async def executor(output, state):
        return output.answer

    tool = SubAgentTool(agent, executor, lambda r, s: None)
    result = await tool.run({}, "go")
    assert result.confidence is None


# ---- ContextManager salience -----------------------------------------


def test_context_manager_default_no_salience_unchanged():
    """Without salience_fn, behavior is unchanged."""
    cm = ContextManager(token_budget=1000, reserve=0)
    assert cm._salience_fn is None


def test_context_manager_salience_fn_stored():
    cm = ContextManager(salience_fn=confidence_salience)
    assert cm._salience_fn is not None


def test_context_manager_safe_salience_returns_one_on_exception():
    """A salience_fn that raises → fall back to 1.0 (best-effort)."""

    def bad_salience(_):
        raise RuntimeError("boom")

    cm = ContextManager(salience_fn=bad_salience)
    assert cm._safe_salience(object()) == 1.0


def test_context_manager_safe_salience_no_fn_returns_one():
    cm = ContextManager(salience_fn=None)
    assert cm._safe_salience(object()) == 1.0
