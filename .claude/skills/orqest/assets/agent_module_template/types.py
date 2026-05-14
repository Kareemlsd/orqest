"""Pydantic input/output shapes for the <NAME> agent.

Add ``self_confidence: float`` to ``<NAME>Output`` if you want zero-cost
metacognition via ``StructuredOutputProtocol``. Otherwise leave it off.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class <NAME>Output(BaseModel):
    """Structured output for the <NAME> agent.

    Tied to Phase A discovery answer 9 (what should the agent return).
    """

    # Replace these with the actual output fields. Examples:
    # summary: str = Field(description="Markdown overview")
    # items: list[str] = Field(default_factory=list, description="...")

    # Optional metacognition field (uncomment to enable StructuredOutputProtocol):
    # self_confidence: float = Field(
    #     default=0.5,
    #     ge=0.0,
    #     le=1.0,
    #     description="Self-rated probability the output satisfies the task.",
    # )
    # uncertain_about: list[str] = Field(default_factory=list)
