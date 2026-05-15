"""Tests for OrqestGEPAAdapter — the GEPA <-> Orqest bridge."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.observability.events import EventBus
from orqest.optimization import (
    Evaluator,
    Genome,
    GoldExample,
    MetricBundle,
    MetricWeights,
    OrqestEvalBatch,
    OrqestGEPAAdapter,
    PromptGene,
)


class _Out(BaseModel):
    answer: str
    confidence: float = 0.7


class _StubAgent(BaseAgent[GlobalState, _Out]):
    async def _run_implementation(
        self, state: GlobalState, **kwargs: Any
    ) -> _Out:
        latest = state.get_latest_message("user") or ""
        result = await self.call_model(latest, state)
        return result.output


def _make_agent(decoded: dict[str, Any]) -> _StubAgent:
    return _StubAgent(
        agent_name="stub",
        system_prompt=decoded.get("system_prompt", "default"),
        output_type=_Out,
        model=TestModel(custom_output_args={"answer": "stubbed", "confidence": 0.8}),
    )


def _score(output: _Out, ex: GoldExample[str, _Out]) -> float:
    return 1.0 if "stub" in output.answer else 0.0


def _make_adapter(*, bus: EventBus | None = None) -> OrqestGEPAAdapter:
    genome = Genome(
        genes=[
            PromptGene(
                name="system_prompt",
                initial="Be concise.",
                constraints="Always answer in one word.",
            )
        ]
    )
    evaluator = Evaluator(agent_factory=_make_agent, score_fn=_score)
    return OrqestGEPAAdapter(genome, evaluator, MetricWeights(), bus=bus)


def _example(text: str = "what is X?") -> GoldExample[str, _Out]:
    return GoldExample[str, _Out](input=text, expected=_Out(answer="stubbed"))


def test_evaluate_returns_orqest_eval_batch():
    adapter = _make_adapter()
    batch = [_example("a"), _example("b")]
    result = adapter.evaluate(batch, {"system_prompt": "Answer briefly."})
    assert isinstance(result, OrqestEvalBatch)
    assert len(result.scores) == 2
    assert len(result.objective_scores or []) == 2
    assert len(result.bundles) == 2


def test_evaluate_decodes_candidate_through_genome():
    """The decoded value should reach the agent_factory verbatim."""
    captured: list[dict[str, Any]] = []

    def factory(decoded: dict[str, Any]) -> _StubAgent:
        captured.append(decoded)
        return _make_agent(decoded)

    genome = Genome(genes=[PromptGene(name="system_prompt", initial="A")])
    evaluator = Evaluator(agent_factory=factory, score_fn=_score)
    adapter = OrqestGEPAAdapter(genome, evaluator, MetricWeights())

    adapter.evaluate([_example()], {"system_prompt": "evolved prompt"})
    assert captured[0]["system_prompt"] == "evolved prompt"


def test_evaluate_objective_scores_carry_per_dimension():
    adapter = _make_adapter()
    result = adapter.evaluate([_example()], {"system_prompt": "x"})
    obj = (result.objective_scores or [{}])[0]
    assert "accuracy" in obj
    assert "cost_usd" in obj
    assert "latency_ms" in obj


def test_capture_traces_false_returns_no_trajectories():
    adapter = _make_adapter()
    result = adapter.evaluate(
        [_example()], {"system_prompt": "x"}, capture_traces=False
    )
    assert result.trajectories is None


def test_capture_traces_true_populates_trajectories():
    adapter = _make_adapter()
    result = adapter.evaluate(
        [_example("a"), _example("b")],
        {"system_prompt": "x"},
        capture_traces=True,
    )
    assert result.trajectories is not None
    assert len(result.trajectories) == 2


def test_make_reflective_dataset_keys_match_components_to_update():
    adapter = _make_adapter()
    result = adapter.evaluate(
        [_example("a"), _example("b")],
        {"system_prompt": "x"},
        capture_traces=True,
    )
    dataset = adapter.make_reflective_dataset(
        candidate={"system_prompt": "x"},
        eval_batch=result,
        components_to_update=["system_prompt"],
    )
    assert set(dataset.keys()) == {"system_prompt"}
    assert len(dataset["system_prompt"]) == 2


def test_make_reflective_dataset_includes_constraints_when_present():
    adapter = _make_adapter()
    result = adapter.evaluate(
        [_example()], {"system_prompt": "x"}, capture_traces=True
    )
    dataset = adapter.make_reflective_dataset(
        candidate={"system_prompt": "x"},
        eval_batch=result,
        components_to_update=["system_prompt"],
    )
    record = dataset["system_prompt"][0]
    assert "Constraints" in record
    assert "one word" in record["Constraints"]


def test_emits_iteration_event_when_bus_provided():
    bus = EventBus()
    received: list[Any] = []

    def listener(event: Any) -> None:
        received.append(event)

    bus.subscribe("optimization.iteration_completed", listener)
    adapter = _make_adapter(bus=bus)
    adapter.evaluate([_example()], {"system_prompt": "x"})
    # Give the fire-and-forget emit a moment to land
    import time

    time.sleep(0.05)
    assert any(
        ev.event_type == "optimization.iteration_completed" for ev in received
    )


@pytest.mark.asyncio
async def test_async_bridge_runs_when_loop_already_present():
    """Inside an async test (== Jupyter-like environment), the adapter must
    still complete via its worker-thread fallback rather than deadlocking.
    """
    adapter = _make_adapter()
    result = adapter.evaluate([_example()], {"system_prompt": "x"})
    assert len(result.bundles) == 1
    assert isinstance(result.bundles[0], MetricBundle)
