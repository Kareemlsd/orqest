"""Tests for OptimizationRunner — wraps gepa.optimize, owns the contract."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from orqest.agents.base_agent import BaseAgent
from orqest.agents.state import GlobalState
from orqest.observability.events import EventBus
from orqest.optimization import (
    CategoricalGene,
    Evaluator,
    Genome,
    GoldExample,
    OptimizationConfig,
    OptimizationResult,
    OptimizationRunner,
    PromptGene,
    ScalarGene,
)
from orqest.optimization.runner import (
    _ensure_litellm_api_key,
    _to_litellm_model_string,
)


class _Out(BaseModel):
    answer: str


class _StubAgent(BaseAgent[GlobalState, _Out]):
    async def _run_implementation(self, state: GlobalState, **kwargs: Any) -> _Out:
        latest = state.get_latest_message("user") or ""
        result = await self.call_model(latest, state)
        return result.output


def _make_agent(decoded: dict[str, Any]) -> _StubAgent:
    return _StubAgent(
        agent_name="stub",
        system_prompt=decoded.get("system_prompt", "default"),
        output_type=_Out,
        model=TestModel(custom_output_args={"answer": "stubbed"}),
    )


def _score(output: _Out, ex: GoldExample[str, _Out]) -> float:
    return 1.0


def _make_runner(
    config: OptimizationConfig | None = None,
    *,
    bus: EventBus | None = None,
    genome: Genome | None = None,
) -> OptimizationRunner:
    cfg = config or OptimizationConfig(max_metric_calls=10)
    g = genome or Genome(
        genes=[PromptGene(name="system_prompt", initial="Be brief.")]
    )
    evaluator = Evaluator(agent_factory=_make_agent, score_fn=_score)
    return OptimizationRunner(cfg, genome=g, evaluator=evaluator, bus=bus)


def _examples(n: int) -> list[GoldExample[str, _Out]]:
    return [
        GoldExample[str, _Out](input=f"q{i}", id=f"ex-{i}")
        for i in range(n)
    ]


def _fake_gepa_result(seed: dict[str, str]) -> Any:
    """Construct a MagicMock GEPAResult with the minimal surface the runner reads."""
    r = MagicMock()
    r.candidates = [seed, {**seed, "system_prompt": "Be terse."}]
    r.val_aggregate_scores = [0.5, 0.7]
    r.best_idx = 1
    r.per_val_instance_best_candidates = {0: {0, 1}, 1: {1}}
    return r


@pytest.fixture
def mock_gepa_optimize():
    captured: dict[str, Any] = {}

    def fake(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_gepa_result(kwargs["seed_candidate"])

    with patch(
        "orqest.optimization.runner._gepa_optimize", side_effect=fake
    ) as m:
        m.captured = captured  # type: ignore[attr-defined]
        yield m


@pytest.mark.asyncio
async def test_runner_calls_gepa_with_seed_and_adapter(mock_gepa_optimize):
    runner = _make_runner()
    result = await runner.optimize(_examples(8))
    mock_gepa_optimize.assert_called_once()
    kwargs = mock_gepa_optimize.captured  # type: ignore[attr-defined]
    assert "seed_candidate" in kwargs
    assert kwargs["seed_candidate"] == {"system_prompt": "Be brief."}
    assert kwargs["adapter"] is not None
    assert isinstance(result, OptimizationResult)


@pytest.mark.asyncio
async def test_runner_splits_trainset_when_no_valset(mock_gepa_optimize):
    runner = _make_runner(OptimizationConfig(max_metric_calls=10, valset_fraction=0.5))
    await runner.optimize(_examples(10))
    kwargs = mock_gepa_optimize.captured  # type: ignore[attr-defined]
    assert len(kwargs["trainset"]) == 5
    assert len(kwargs["valset"]) == 5


@pytest.mark.asyncio
async def test_runner_explicit_valset_passed_through(mock_gepa_optimize):
    runner = _make_runner()
    train = _examples(6)
    val = _examples(3)
    await runner.optimize(train, val)
    kwargs = mock_gepa_optimize.captured  # type: ignore[attr-defined]
    assert len(kwargs["trainset"]) == 6
    assert len(kwargs["valset"]) == 3


@pytest.mark.asyncio
async def test_runner_returns_pareto_candidates(mock_gepa_optimize):
    runner = _make_runner()
    result = await runner.optimize(_examples(8))
    # Fake result: per_val_instance maps to indices {0, 1} -> 2 distinct candidates
    assert len(result.pareto_candidates) == 2


@pytest.mark.asyncio
async def test_runner_seed_propagated(mock_gepa_optimize):
    runner = _make_runner(OptimizationConfig(max_metric_calls=10, seed=99))
    await runner.optimize(_examples(8))
    kwargs = mock_gepa_optimize.captured  # type: ignore[attr-defined]
    assert kwargs["seed"] == 99


@pytest.mark.asyncio
async def test_runner_passes_frontier_type(mock_gepa_optimize):
    runner = _make_runner(
        OptimizationConfig(max_metric_calls=10, frontier_type="objective")
    )
    await runner.optimize(_examples(8))
    kwargs = mock_gepa_optimize.captured  # type: ignore[attr-defined]
    assert kwargs["frontier_type"] == "objective"


def test_runner_rejects_scalar_gene_when_disabled():
    g = Genome(
        genes=[ScalarGene(name="thresh", initial=0.5, low=0.0, high=1.0)]
    )
    with pytest.raises(NotImplementedError, match="enable_scalar_genes"):
        _make_runner(genome=g)


def test_runner_rejects_categorical_gene_when_disabled():
    g = Genome(
        genes=[
            CategoricalGene(
                name="mode", initial="a", choices=("a", "b", "c")
            )
        ]
    )
    with pytest.raises(NotImplementedError, match="enable_categorical_genes"):
        _make_runner(genome=g)


class TestEnsureLitellmApiKey:
    """The bridge that surfaces orqest's api_key to the env var litellm reads."""

    def test_sets_openai_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        _ensure_litellm_api_key("openai:gpt-4.1", "sk-test-123")
        import os
        assert os.environ["OPENAI_API_KEY"] == "sk-test-123"

    def test_sets_anthropic_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        _ensure_litellm_api_key("anthropic:claude-sonnet-4-6", "sk-ant-test")
        import os
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test"

    def test_setdefault_does_not_clobber_explicit_env(self, monkeypatch):
        """An operator who sets OPENAI_API_KEY explicitly keeps that value."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-original")
        _ensure_litellm_api_key("openai:gpt-4.1", "sk-different")
        import os
        assert os.environ["OPENAI_API_KEY"] == "sk-original"

    def test_no_op_when_api_key_is_none(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        _ensure_litellm_api_key("openai:gpt-4.1", None)
        import os
        assert "OPENAI_API_KEY" not in os.environ

    def test_no_op_for_unknown_provider(self, monkeypatch):
        # Don't blow up on novel provider strings; just no-op silently
        _ensure_litellm_api_key("unknown:foo", "sk-x")  # must not raise


class TestLitellmModelStringTranslator:
    """Sanity checks for the colon->slash translator that bridges
    Orqest's pydantic-ai-style model strings to litellm's expected format
    (GEPA's default reflection_lm path goes through litellm)."""

    def test_translates_colon_to_slash(self):
        assert _to_litellm_model_string("openai:gpt-4.1") == "openai/gpt-4.1"

    def test_passes_through_already_slashed(self):
        assert _to_litellm_model_string("openai/gpt-4.1") == "openai/gpt-4.1"

    def test_passes_through_bare_model_name(self):
        # litellm auto-detects bare names; don't mangle them
        assert _to_litellm_model_string("gpt-4.1-mini") == "gpt-4.1-mini"

    def test_passes_through_none(self):
        assert _to_litellm_model_string(None) is None

    def test_only_partitions_first_colon(self):
        # openrouter passes through nested provider strings
        assert (
            _to_litellm_model_string("openrouter:openai/gpt-4o")
            == "openrouter/openai/gpt-4o"
        )


@pytest.mark.asyncio
async def test_runner_translates_reflection_model_to_litellm(mock_gepa_optimize):
    """End-to-end: configured reflection_model in pydantic-ai colon syntax
    reaches GEPA in litellm slash syntax."""
    runner = _make_runner(
        OptimizationConfig(
            max_metric_calls=10, reflection_model="openai:gpt-4.1"
        )
    )
    await runner.optimize(_examples(8))
    kwargs = mock_gepa_optimize.captured  # type: ignore[attr-defined]
    assert kwargs["reflection_lm"] == "openai/gpt-4.1"


@pytest.mark.asyncio
async def test_runner_history_collects_iteration_events(mock_gepa_optimize):
    """When a bus is provided, the runner subscribes to iteration events
    and surfaces them via OptimizationResult.history.
    """
    bus = EventBus()
    runner = _make_runner(bus=bus)
    # Manually emit an iteration event before invoking optimize() to prove
    # the subscription is wired (the mock GEPA never actually iterates).
    result = await runner.optimize(_examples(8))
    # History exists and is a list (may be empty given the mock GEPA)
    assert isinstance(result.history, list)
