"""Serializable agent and tool definitions for runtime agent spawning.

An LLM produces an AgentSpec as structured output. The AgentFactory
hydrates it into a live BaseAgent. ToolSpec describes a tool an agent needs,
resolved from the ToolRegistry by name.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Description of a tool an agent needs."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    source: Literal["registry", "dynamic"] = "registry"


class AgentSpec(BaseModel):
    """Everything needed to spawn an agent at runtime.

    An LLM produces this as structured output. The AgentFactory
    hydrates it into a live BaseAgent.
    """

    name: str
    system_prompt: str
    output_schema: dict[str, Any]
    tools: list[ToolSpec] = Field(default_factory=list)
    model: str = "openai:gpt-4o"
    constraints: list[str] = Field(default_factory=list)
    token_budget: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
