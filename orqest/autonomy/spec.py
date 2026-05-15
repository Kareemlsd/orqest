"""Serializable agent and tool definitions for runtime agent spawning.

An LLM produces an AgentSpec as structured output. The AgentFactory
hydrates it into a live BaseAgent. ToolSpec describes a tool an agent needs,
resolved from the ToolRegistry by name.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Description of a tool an agent needs.

    The ``name`` is resolved against :class:`ToolRegistry` at spawn time.
    ``parameters`` is a JSON-Schema-shaped dict carried for the LLM's
    benefit (it never reaches the registered tool — that contract lives
    on the tool itself).
    """

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentSpec(BaseModel):
    """Everything needed to spawn an agent at runtime.

    An LLM produces this as structured output. The AgentFactory
    hydrates it into a live BaseAgent.
    """

    name: str
    system_prompt: str
    output_schema: dict[str, Any]
    tools: list[ToolSpec] = Field(default_factory=list)
    model: str = "openai:gpt-4.1"
    constraints: list[str] = Field(default_factory=list)
