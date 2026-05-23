"""Genes — what's evolvable in an Orqest agentic system.

A :class:`Genome` is a typed inventory of mutable knobs. The optimizer
encodes it into GEPA's wire format (``dict[str, str]``) for evolution and
decodes proposed mutations back into typed Python values.

Three gene kinds, all serializable, discriminated by ``kind``:

* :class:`PromptGene` — a string prompt slot. The bread-and-butter of W1.
* :class:`ScalarGene` — a bounded float (with optional quantization grid).
  Wired but gated by :attr:`OptimizationConfig.enable_scalar_genes`.
* :class:`CategoricalGene` — a fixed-set string choice. Same gating story.

Decode is **resilient**: a malformed proposal from the reflection LLM
(missing key, unparseable scalar, out-of-set categorical) falls back to
the gene's ``initial`` value rather than raising. GEPA's mutation engine
sometimes returns dirty payloads; we'd rather lose one iteration than
crash the run.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromptGene(BaseModel):
    """A prompt-string slot — the canonical GEPA target."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["prompt"] = "prompt"
    name: str
    """Logical slot identifier, e.g. ``"researcher.system_prompt"``. Must
    match the key the consumer hands to :func:`apply_result` (or to a
    custom ``agent_factory``)."""

    initial: str
    """Seed prompt text. Becomes the W0 candidate GEPA mutates from."""

    constraints: str | None = None
    """Optional natural-language guardrail surfaced to the reflection LLM
    in :meth:`OrqestGEPAAdapter.make_reflective_dataset`. Use it to encode
    invariants the optimizer must not break (e.g. *"Must abstain on
    ambiguous goals"*)."""

    def encode(self) -> str:
        return self.initial

    def decode(self, value: str | None) -> str:
        if value is None:
            return self.initial
        return value


class ScalarGene(BaseModel):
    """A bounded float gene. Decode clamps + optional quantization."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["scalar"] = "scalar"
    name: str
    initial: float
    low: float
    high: float
    quantize: float | None = None
    """When set, decode snaps to the nearest multiple of this grid step."""

    @model_validator(mode="after")
    def _validate_bounds(self) -> ScalarGene:
        if self.high <= self.low:
            raise ValueError(
                f"ScalarGene.high ({self.high}) must be > low ({self.low})"
            )
        if not self.low <= self.initial <= self.high:
            raise ValueError(
                f"ScalarGene.initial ({self.initial}) must be within [low, high]"
            )
        if self.quantize is not None and self.quantize <= 0:
            raise ValueError("ScalarGene.quantize must be > 0 when set")
        return self

    def encode(self) -> str:
        return str(self.initial)

    def decode(self, value: str | None) -> float:
        if value is None:
            return self.initial
        try:
            f = float(value)
        except (TypeError, ValueError):
            return self.initial
        f = max(self.low, min(self.high, f))
        if self.quantize is not None:
            steps = round((f - self.low) / self.quantize)
            f = self.low + steps * self.quantize
            f = max(self.low, min(self.high, f))
        return f


class CategoricalGene(BaseModel):
    """A fixed-set string choice. Decode validates against ``choices``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["categorical"] = "categorical"
    name: str
    initial: str
    choices: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_initial_in_choices(self) -> CategoricalGene:
        if self.initial not in self.choices:
            raise ValueError(
                f"CategoricalGene.initial ({self.initial!r}) "
                f"must be one of {self.choices!r}"
            )
        if len(self.choices) < 2:
            raise ValueError("CategoricalGene needs at least 2 choices")
        return self

    def encode(self) -> str:
        return self.initial

    def decode(self, value: str | None) -> str:
        if value is None or value not in self.choices:
            return self.initial
        return value


Gene = Annotated[
    PromptGene | ScalarGene | CategoricalGene,
    Field(discriminator="kind"),
]


class Genome(BaseModel):
    """An ordered collection of genes — the mutable surface of one
    optimization run.

    The optimizer encodes the genome to GEPA's seed format via
    :meth:`to_seed`, GEPA proposes candidate mutations as the same
    ``dict[str, str]`` shape, and :meth:`decode` round-trips them back to
    typed Python values consumed by the consumer's ``agent_factory``.
    """

    genes: list[Gene]

    def to_seed(self) -> dict[str, str]:
        """Encode the genome into GEPA's ``seed_candidate`` format."""
        return {g.name: g.encode() for g in self.genes}

    def decode(self, candidate: dict[str, str]) -> dict[str, Any]:
        """Decode a GEPA-proposed candidate back into typed values.

        Resilient by design: missing or malformed entries fall back to
        the gene's ``initial`` rather than raising.
        """
        return {g.name: g.decode(candidate.get(g.name)) for g in self.genes}

    def gene_kinds(self) -> set[str]:
        """Set of gene kinds present — useful for the runner's gating
        check (``enable_scalar_genes`` / ``enable_categorical_genes``).
        """
        return {g.kind for g in self.genes}
