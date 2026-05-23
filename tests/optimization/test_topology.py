"""Tests for orqest.optimization.topology — TopologyGene + TopologyEvaluator."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.optimization.evaluator import GoldExample
from orqest.optimization.topology import (
    TopologyEvaluator,
    TopologyGene,
    unpack_topology_output,
)
from orqest.orchestration.hydrate import CallableRegistry
from orqest.orchestration.loop import LoopResult
from orqest.orchestration.parallel import ParallelResult
from orqest.orchestration.spec import (
    AgentStepSpec,
    ParallelSpec,
    PipelineSpec,
    PipelineStepEntry,
    RouterSpec,
    RouteSpec,
)


# --- Fixtures ----------------------------------------------------------------


class _Out(BaseModel):
    answer: str


class _StubAgent(BaseAgent[GlobalState, _Out]):
    async def _run_implementation(self, state: GlobalState, **kwargs: Any) -> _Out:
        latest = state.get_latest_message("user") or ""
        result = await self.call_model(latest, state)
        return result.output


def _make_factory(label: str):
    def _f() -> _StubAgent:
        return _StubAgent(
            agent_name=label,
            system_prompt=f"you are {label}",
            output_type=_Out,
            model=TestModel(custom_output_args={"answer": f"{label}-out"}),
        )

    return _f


@pytest.fixture
def agents():
    return {
        "cot": _make_factory("cot"),
        "verifier": _make_factory("verifier"),
    }


@pytest.fixture
def callables():
    cr = CallableRegistry()
    cr.register("is_long", lambda x: len(str(x)) > 5)
    return cr


@pytest.fixture
def seed_pipeline():
    return PipelineSpec(
        steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="cot"))]
    )


# --- TopologyGene ------------------------------------------------------------


class TestTopologyGene:
    def test_construction_defaults(self, seed_pipeline):
        gene = TopologyGene(name="main", initial=seed_pipeline)
        assert gene.kind == "topology"
        assert gene.name == "main"
        assert gene.constraints is None
        assert gene.allowed_step_kinds == ("agent_step", "function_step")
        assert gene.max_depth == 4

    def test_encode_returns_json_string(self, seed_pipeline):
        gene = TopologyGene(name="main", initial=seed_pipeline)
        encoded = gene.encode()
        assert isinstance(encoded, str)
        assert '"kind":"pipeline"' in encoded

    def test_decode_round_trip(self, seed_pipeline):
        gene = TopologyGene(name="main", initial=seed_pipeline)
        decoded = gene.decode(gene.encode())
        assert decoded == seed_pipeline

    def test_decode_none_falls_back_to_initial(self, seed_pipeline):
        gene = TopologyGene(name="main", initial=seed_pipeline)
        assert gene.decode(None) == seed_pipeline

    def test_decode_malformed_json_falls_back(self, seed_pipeline):
        gene = TopologyGene(name="main", initial=seed_pipeline)
        assert gene.decode("not json at all") == seed_pipeline

    def test_decode_bad_schema_falls_back(self, seed_pipeline):
        gene = TopologyGene(name="main", initial=seed_pipeline)
        # Valid JSON but unknown kind
        assert gene.decode('{"kind": "ghost"}') == seed_pipeline

    def test_decode_valid_alternative_topology(self, seed_pipeline):
        gene = TopologyGene(name="main", initial=seed_pipeline)
        alt = ParallelSpec(steps=[AgentStepSpec(agent_name="cot")])
        decoded = gene.decode(alt.model_dump_json())
        assert decoded == alt

    def test_constraints_field(self, seed_pipeline):
        gene = TopologyGene(
            name="main",
            initial=seed_pipeline,
            constraints="must include verifier as last step",
        )
        assert gene.constraints == "must include verifier as last step"

    def test_frozen(self, seed_pipeline):
        gene = TopologyGene(name="main", initial=seed_pipeline)
        from pydantic import ValidationError as VE

        with pytest.raises(VE):
            gene.name = "other"  # type: ignore[misc]


# --- unpack_topology_output ------------------------------------------------


class TestUnpackTopologyOutput:
    def test_parallel_result_returns_merged(self):
        pr = ParallelResult(outputs=["a", "b"], errors=[None, None], merged="MERGED")
        assert unpack_topology_output(pr) == "MERGED"

    def test_loop_result_returns_output(self):
        lr = LoopResult(output="DONE", iterations=3, exit_reason="passed")
        assert unpack_topology_output(lr) == "DONE"

    def test_bare_value_passthrough(self):
        assert unpack_topology_output("hello") == "hello"

    def test_object_with_output_attr(self):
        class _R:
            output = "o"

        assert unpack_topology_output(_R()) == "o"


# --- TopologyEvaluator ------------------------------------------------------


def _score_cot(out: _Out, _ex: GoldExample[Any, Any]) -> float:
    return 1.0 if out.answer == "cot-out" else 0.0


@pytest.mark.asyncio
async def test_evaluate_one_pipeline_scores_correctly(agents, callables, seed_pipeline):
    ev = TopologyEvaluator(
        score_fn=_score_cot,
        callable_registry=callables,
        agent_registry=agents,
    )
    bundle = await ev.evaluate_one(
        decoded={"main": seed_pipeline},
        example=GoldExample[str, _Out](input="hi"),
    )
    assert bundle.accuracy == 1.0
    assert bundle.raw["n_agents"] == 1
    assert bundle.raw["depth"] == 1


@pytest.mark.asyncio
async def test_evaluate_one_parallel_unpacks_merged(agents, callables):
    spec = ParallelSpec(
        steps=[AgentStepSpec(agent_name="cot")], merge="first_wins"
    )
    ev = TopologyEvaluator(
        score_fn=_score_cot,
        callable_registry=callables,
        agent_registry=agents,
    )
    bundle = await ev.evaluate_one(
        decoded={"main": spec}, example=GoldExample[str, _Out](input="hi")
    )
    assert bundle.accuracy == 1.0  # first_wins surfaces cot-out


@pytest.mark.asyncio
async def test_evaluate_one_missing_gene_returns_zero_accuracy(agents, callables):
    ev = TopologyEvaluator(
        score_fn=_score_cot,
        callable_registry=callables,
        agent_registry=agents,
    )
    bundle = await ev.evaluate_one(
        decoded={}, example=GoldExample[str, _Out](input="hi")
    )
    assert bundle.accuracy == 0.0
    assert bundle.raw["error_type"] == "MissingGene"


@pytest.mark.asyncio
async def test_evaluate_one_hydration_failure_captures_error(callables):
    """Missing agent in registry → KeyError → captured as zero-accuracy bundle."""
    spec = PipelineSpec(
        steps=[PipelineStepEntry(operation=AgentStepSpec(agent_name="ghost"))]
    )
    ev = TopologyEvaluator(
        score_fn=_score_cot,
        callable_registry=callables,
        agent_registry={},  # empty registry
    )
    bundle = await ev.evaluate_one(
        decoded={"main": spec}, example=GoldExample[str, _Out](input="hi")
    )
    assert bundle.accuracy == 0.0
    assert bundle.raw["error_type"] == "KeyError"
    # Structural metrics still reported
    assert bundle.raw["n_agents"] == 1


@pytest.mark.asyncio
async def test_evaluate_batch_aggregates(agents, callables, seed_pipeline):
    ev = TopologyEvaluator(
        score_fn=_score_cot,
        callable_registry=callables,
        agent_registry=agents,
    )
    bundles = await ev.evaluate_batch(
        decoded={"main": seed_pipeline},
        batch=[
            GoldExample[str, _Out](input=f"q{i}") for i in range(3)
        ],
    )
    assert len(bundles) == 3
    assert all(b.accuracy == 1.0 for b in bundles)


@pytest.mark.asyncio
async def test_evaluate_one_records_depth_and_n_agents_for_nested(agents, callables):
    """A 2-step Pipeline should report n_agents=2, depth=1."""
    spec = PipelineSpec(
        steps=[
            PipelineStepEntry(operation=AgentStepSpec(agent_name="cot")),
            PipelineStepEntry(operation=AgentStepSpec(agent_name="verifier")),
        ]
    )
    ev = TopologyEvaluator(
        score_fn=_score_cot,
        callable_registry=callables,
        agent_registry=agents,
    )
    bundle = await ev.evaluate_one(
        decoded={"main": spec}, example=GoldExample[str, _Out](input="hi")
    )
    # Last step is verifier, score returns 0
    assert bundle.accuracy == 0.0
    assert bundle.raw["n_agents"] == 2
    assert bundle.raw["depth"] == 1


@pytest.mark.asyncio
async def test_topology_gene_name_override(agents, callables, seed_pipeline):
    """Custom topology_gene_name routes the lookup correctly."""
    ev = TopologyEvaluator(
        score_fn=_score_cot,
        callable_registry=callables,
        agent_registry=agents,
        topology_gene_name="my_topo",
    )
    bundle = await ev.evaluate_one(
        decoded={"my_topo": seed_pipeline},
        example=GoldExample[str, _Out](input="hi"),
    )
    assert bundle.accuracy == 1.0
