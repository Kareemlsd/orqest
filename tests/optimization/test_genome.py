"""Tests for Genome / PromptGene / ScalarGene / CategoricalGene."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.optimization import (
    CategoricalGene,
    Genome,
    PromptGene,
    ScalarGene,
)


class TestPromptGene:
    def test_round_trip(self):
        gene = PromptGene(name="researcher.system_prompt", initial="Be precise.")
        genome = Genome(genes=[gene])
        seed = genome.to_seed()
        assert seed == {"researcher.system_prompt": "Be precise."}

    def test_constraints_attached(self):
        gene = PromptGene(
            name="planner",
            initial="Decompose the goal.",
            constraints="Always abstain on ambiguous goals.",
        )
        genome = Genome(genes=[gene])
        decoded = genome.decode({"planner": "New planner prompt."})
        assert decoded["planner"] == "New planner prompt."

    def test_decode_falls_back_when_key_missing(self):
        """A reflection LLM that fails to emit a slot should fall back to initial."""
        gene = PromptGene(name="researcher", initial="Original.")
        genome = Genome(genes=[gene])
        decoded = genome.decode({})  # missing key
        assert decoded["researcher"] == "Original."


class TestScalarGene:
    def test_clamp_high(self):
        gene = ScalarGene(name="threshold", initial=0.5, low=0.0, high=1.0)
        genome = Genome(genes=[gene])
        decoded = genome.decode({"threshold": "1.5"})
        assert decoded["threshold"] == 1.0

    def test_clamp_low(self):
        gene = ScalarGene(name="threshold", initial=0.5, low=0.0, high=1.0)
        genome = Genome(genes=[gene])
        decoded = genome.decode({"threshold": "-0.5"})
        assert decoded["threshold"] == 0.0

    def test_quantize(self):
        gene = ScalarGene(
            name="threshold", initial=0.5, low=0.0, high=1.0, quantize=0.1
        )
        genome = Genome(genes=[gene])
        decoded = genome.decode({"threshold": "0.37"})
        # Snap to nearest 0.1
        assert decoded["threshold"] == pytest.approx(0.4)

    def test_decode_invalid_falls_back_to_initial(self):
        gene = ScalarGene(name="threshold", initial=0.5, low=0.0, high=1.0)
        genome = Genome(genes=[gene])
        decoded = genome.decode({"threshold": "not-a-number"})
        assert decoded["threshold"] == 0.5

    def test_high_must_exceed_low(self):
        with pytest.raises(ValidationError):
            ScalarGene(name="x", initial=0.5, low=1.0, high=0.0)


class TestCategoricalGene:
    def test_decode_known_choice(self):
        gene = CategoricalGene(
            name="protocol",
            initial="structured",
            choices=("structured", "self_rating", "ensemble"),
        )
        genome = Genome(genes=[gene])
        decoded = genome.decode({"protocol": "ensemble"})
        assert decoded["protocol"] == "ensemble"

    def test_unknown_choice_falls_back_to_initial(self):
        gene = CategoricalGene(
            name="protocol",
            initial="structured",
            choices=("structured", "self_rating"),
        )
        genome = Genome(genes=[gene])
        decoded = genome.decode({"protocol": "unknown_choice"})
        assert decoded["protocol"] == "structured"

    def test_initial_must_be_in_choices(self):
        with pytest.raises(ValidationError):
            CategoricalGene(
                name="protocol",
                initial="not_a_choice",
                choices=("a", "b", "c"),
            )


class TestGenome:
    def test_seed_keys_match_gene_names(self):
        genome = Genome(
            genes=[
                PromptGene(name="agent_a.prompt", initial="A"),
                PromptGene(name="agent_b.prompt", initial="B"),
            ]
        )
        seed = genome.to_seed()
        assert set(seed.keys()) == {"agent_a.prompt", "agent_b.prompt"}

    def test_decode_handles_mixed_genome(self):
        genome = Genome(
            genes=[
                PromptGene(name="prompt", initial="hello"),
                ScalarGene(name="thresh", initial=0.5, low=0.0, high=1.0),
                CategoricalGene(
                    name="mode", initial="a", choices=("a", "b")
                ),
            ]
        )
        decoded = genome.decode(
            {"prompt": "evolved hello", "thresh": "0.7", "mode": "b"}
        )
        assert decoded["prompt"] == "evolved hello"
        assert decoded["thresh"] == 0.7
        assert decoded["mode"] == "b"
