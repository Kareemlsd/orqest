"""``EnrichedOutput[OutputT]`` — agent output paired with self-assessment.

A thin wrapper that decouples *what the agent produced* from *what the
agent thinks of what it produced*. Generic over ``OutputT`` so typing
flows unchanged through Pipeline / RefinementLoop / SubAgentTool.

All metacognitive fields are best-effort: a :class:`ConfidenceProtocol`
that fails or returns ill-formed data falls back to ``confidence=None``,
``capability_boundary=False``, empty ``uncertainty_targets``.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

OutputT = TypeVar("OutputT")


class EnrichedOutput(BaseModel, Generic[OutputT]):
    """Agent output paired with the agent's own self-assessment."""

    output: OutputT = Field(
        description="The agent's structured output — exactly what BaseAgent.run "
        "returned before enrichment."
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Self-rated probability that the output satisfies the "
        "agent's task. None when no protocol ran or the protocol failed. "
        "Calibration is protocol-defined.",
    )
    uncertainty_targets: list[str] = Field(
        default_factory=list,
        description="Free-text identifiers for assumptions or sub-claims the "
        "agent flagged as the bottleneck on confidence.",
    )
    capability_boundary: bool = Field(
        default=False,
        description="True iff the agent reports the task is outside what it "
        "can verify (e.g. requires a tool it lacks, knowledge after its "
        "cutoff, or a subjective judgement). Distinct from low confidence.",
    )
    protocol_name: str | None = Field(
        default=None,
        description="Name of the ConfidenceProtocol that produced this "
        "enrichment. None when no protocol ran.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Protocol-defined free space (sample_count, "
        "rating_prompt_hash, protocol_error). Never load-bearing — UI / "
        "telemetry only.",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)
