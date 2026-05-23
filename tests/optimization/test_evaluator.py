"""Tests for the Evaluator wrapping fresh agents around gold examples."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.optimization import Evaluator, GoldExample, MetricBundle


class _SummaryOutput(BaseModel):
    answer: str
    confidence: float = 0.7


class _StubAgent(BaseAgent[GlobalState, _SummaryOutput]):
    """Real BaseAgent — uses self.call_model so TestModel's custom_output_args
    actually flows through (otherwise we'd be mocking the model layer twice).
    """

    async def _run_implementation(self, state: GlobalState, **kwargs: Any) -> _SummaryOutput:
        latest = state.get_latest_message("user") or ""
        result = await self.call_model(latest, state)
        return result.output


def _make_agent(decoded: dict[str, Any]) -> _StubAgent:
    return _StubAgent(
        agent_name="stub",
        system_prompt=decoded.get("system_prompt", "default"),
        output_type=_SummaryOutput,
        model=TestModel(custom_output_args={"answer": "stubbed", "confidence": 0.9}),
    )


def _score(output: _SummaryOutput, ex: GoldExample[str, _SummaryOutput]) -> float:
    if ex.expected is None:
        return 1.0 if output.answer else 0.0
    return 1.0 if ex.expected.answer in output.answer else 0.0


@pytest.mark.asyncio
async def test_evaluate_one_returns_bundle_with_accuracy():
    evaluator = Evaluator(agent_factory=_make_agent, score_fn=_score)
    bundle = await evaluator.evaluate_one(
        decoded={"system_prompt": "Be brief."},
        example=GoldExample[str, _SummaryOutput](
            input="hello",
            expected=_SummaryOutput(answer="stubbed", confidence=0.5),
        ),
    )
    assert isinstance(bundle, MetricBundle)
    assert bundle.accuracy == 1.0


@pytest.mark.asyncio
async def test_evaluate_batch_aggregates_n_examples():
    evaluator = Evaluator(agent_factory=_make_agent, score_fn=_score)
    batch = [
        GoldExample[str, _SummaryOutput](
            input=f"q{i}",
            expected=_SummaryOutput(answer="stubbed"),
        )
        for i in range(4)
    ]
    bundles = await evaluator.evaluate_batch({"system_prompt": "x"}, batch)
    assert len(bundles) == 4
    assert all(b.accuracy == 1.0 for b in bundles)


@pytest.mark.asyncio
async def test_evaluator_captures_latency():
    evaluator = Evaluator(agent_factory=_make_agent, score_fn=_score)
    bundle = await evaluator.evaluate_one(
        {"system_prompt": "x"},
        GoldExample[str, _SummaryOutput](input="hi"),
    )
    assert bundle.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_evaluator_captures_cost_when_estimator_provided():
    captured: list[Any] = []

    def estimator(usage: Any) -> float:
        captured.append(usage)
        return 0.123

    evaluator = Evaluator(
        agent_factory=_make_agent,
        score_fn=_score,
        cost_estimator=estimator,
    )
    bundle = await evaluator.evaluate_one(
        {"system_prompt": "x"},
        GoldExample[str, _SummaryOutput](input="hi"),
    )
    assert bundle.cost_usd == 0.123


@pytest.mark.asyncio
async def test_evaluator_extracts_confidence_from_output_attr():
    # Score_fn returns 1.0; output has confidence=0.9 (from TestModel's custom_output_args)
    evaluator = Evaluator(
        agent_factory=_make_agent,
        score_fn=_score,
        confidence_protocol=object(),  # any non-None value enables extraction
    )
    bundle = await evaluator.evaluate_one(
        {"system_prompt": "x"},
        GoldExample[str, _SummaryOutput](input="hi"),
    )
    # The stubbed agent's output has confidence=0.9
    assert bundle.confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_evaluator_returns_zero_accuracy_on_agent_exception():
    """The GEPAAdapter Protocol forbids raising for per-example failures."""

    def broken_factory(_decoded: dict[str, Any]) -> _StubAgent:
        raise RuntimeError("agent construction blew up")

    evaluator = Evaluator(agent_factory=broken_factory, score_fn=_score)
    bundle = await evaluator.evaluate_one(
        {"system_prompt": "x"},
        GoldExample[str, _SummaryOutput](input="hi"),
    )
    assert bundle.accuracy == 0.0
    assert "error" in bundle.raw
    assert "agent construction blew up" in bundle.raw["error"]


@pytest.mark.asyncio
async def test_agent_factory_called_per_evaluation():
    """No accidental agent reuse across evaluations."""
    call_count = 0

    def counting_factory(decoded: dict[str, Any]) -> _StubAgent:
        nonlocal call_count
        call_count += 1
        return _make_agent(decoded)

    evaluator = Evaluator(agent_factory=counting_factory, score_fn=_score)
    batch = [
        GoldExample[str, _SummaryOutput](input=f"q{i}") for i in range(3)
    ]
    await evaluator.evaluate_batch({"system_prompt": "x"}, batch)
    assert call_count == 3


# --- n_trials_per_example tests ---------------------------------------


def test_evaluator_rejects_zero_or_negative_trials():
    with pytest.raises(ValueError, match=">= 1"):
        Evaluator(agent_factory=_make_agent, score_fn=_score, n_trials_per_example=0)
    with pytest.raises(ValueError, match=">= 1"):
        Evaluator(agent_factory=_make_agent, score_fn=_score, n_trials_per_example=-1)


@pytest.mark.asyncio
async def test_evaluate_one_default_n_trials_unchanged_behavior():
    """Default n_trials_per_example=1 preserves the legacy bundle shape:
    n_trials=1, stdev=None — identical to pre-change semantics."""
    evaluator = Evaluator(agent_factory=_make_agent, score_fn=_score)
    bundle = await evaluator.evaluate_one(
        {"system_prompt": "x"},
        GoldExample[str, _SummaryOutput](
            input="q", expected=_SummaryOutput(answer="stubbed")
        ),
    )
    assert bundle.n_trials == 1
    assert bundle.stdev is None


@pytest.mark.asyncio
async def test_evaluate_one_multi_trial_aggregates_to_single_bundle():
    """n_trials_per_example=3 runs 3 trials and aggregates to one bundle."""
    factory_calls = 0

    def counting_factory(decoded: dict[str, Any]) -> _StubAgent:
        nonlocal factory_calls
        factory_calls += 1
        return _make_agent(decoded)

    evaluator = Evaluator(
        agent_factory=counting_factory,
        score_fn=_score,
        n_trials_per_example=3,
    )
    bundle = await evaluator.evaluate_one(
        {"system_prompt": "x"},
        GoldExample[str, _SummaryOutput](
            input="q", expected=_SummaryOutput(answer="stubbed")
        ),
    )
    assert factory_calls == 3, "fresh agent per trial"
    assert bundle.n_trials == 3
    # Three trials all scored 1.0 (TestModel deterministic) → mean 1.0, stdev 0
    assert bundle.accuracy == pytest.approx(1.0)
    assert bundle.stdev is not None
    assert bundle.stdev["accuracy"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_evaluate_one_multi_trial_averages_variable_scores():
    """When scores vary across trials, the aggregate reflects mean + stdev."""
    score_seq = [1.0, 0.0, 1.0]
    idx = [0]

    def varying_score(output: _SummaryOutput, ex: GoldExample[str, _SummaryOutput]) -> float:
        v = score_seq[idx[0] % len(score_seq)]
        idx[0] += 1
        return v

    evaluator = Evaluator(
        agent_factory=_make_agent,
        score_fn=varying_score,
        n_trials_per_example=3,
    )
    bundle = await evaluator.evaluate_one(
        {"system_prompt": "x"},
        GoldExample[str, _SummaryOutput](input="q"),
    )
    assert bundle.n_trials == 3
    assert bundle.accuracy == pytest.approx(2.0 / 3.0)
    assert bundle.stdev is not None
    assert bundle.stdev["accuracy"] > 0.0  # genuine dispersion


@pytest.mark.asyncio
async def test_evaluate_one_multi_trial_all_failures_keeps_error():
    """When every trial fails, the aggregate keeps the failure info (not a
    misleading 0.0 averaged accuracy with stdev=0)."""

    def failing_factory(decoded: dict[str, Any]) -> _StubAgent:
        raise RuntimeError("agent construction blew up")

    evaluator = Evaluator(
        agent_factory=failing_factory,
        score_fn=_score,
        n_trials_per_example=3,
    )
    bundle = await evaluator.evaluate_one(
        {"system_prompt": "x"},
        GoldExample[str, _SummaryOutput](input="q"),
    )
    # Failure preserved + multi-trial annotation
    assert "error" in bundle.raw
    assert "agent construction blew up" in bundle.raw["error"]
    assert bundle.raw["aggregation_note"].startswith("all 3 trials failed")
    assert bundle.raw["n_trials_attempted"] == 3


@pytest.mark.asyncio
async def test_evaluate_batch_propagates_n_trials_setting():
    """evaluate_batch routes through evaluate_one — multi-trial config applies
    to every example uniformly."""
    factory_calls = 0

    def counting_factory(decoded: dict[str, Any]) -> _StubAgent:
        nonlocal factory_calls
        factory_calls += 1
        return _make_agent(decoded)

    evaluator = Evaluator(
        agent_factory=counting_factory,
        score_fn=_score,
        n_trials_per_example=2,
    )
    batch = [GoldExample[str, _SummaryOutput](input=f"q{i}") for i in range(3)]
    bundles = await evaluator.evaluate_batch({"system_prompt": "x"}, batch)
    assert len(bundles) == 3
    assert all(b.n_trials == 2 for b in bundles)
    assert factory_calls == 3 * 2  # 3 examples × 2 trials
