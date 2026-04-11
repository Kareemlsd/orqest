"""Tests for AgentFactory — spawning live agents from AgentSpec."""
from __future__ import annotations

import pytest
from pydantic import BaseModel
from pydantic_ai import Tool
from pydantic_ai.models.test import TestModel

from orqest.agents.state import GlobalState
from orqest.autonomy.factory import AgentFactory, DynamicAgent
from orqest.autonomy.registry import ToolRegistry
from orqest.autonomy.spec import AgentSpec, ToolSpec


def _basic_spec(**overrides) -> AgentSpec:
    """Create an AgentSpec with sensible defaults for testing."""
    defaults = {
        "name": "test_agent",
        "system_prompt": "You are a test agent.",
        "output_schema": {
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    }
    defaults.update(overrides)
    return AgentSpec(**defaults)


def _make_tool(name: str) -> Tool:
    async def _fn(query: str) -> str:
        return query

    _fn.__name__ = name
    _fn.__qualname__ = name
    return Tool(_fn, name=name)


class TestAgentFactory:
    def test_spawn_creates_dynamic_agent(self):
        factory = AgentFactory()
        spec = _basic_spec()
        agent = factory.spawn(spec, model=TestModel())
        assert isinstance(agent, DynamicAgent)
        assert agent.agent_name == "test_agent"

    def test_spawn_string_output_schema(self):
        factory = AgentFactory()
        spec = _basic_spec(
            output_schema={
                "properties": {
                    "title": {"type": "string", "description": "The title"},
                    "count": {"type": "integer"},
                },
                "required": ["title"],
            }
        )
        agent = factory.spawn(spec, model=TestModel())
        output_type = agent.output_type
        fields = output_type.model_fields
        assert "title" in fields
        assert "count" in fields

    def test_spawn_list_output_field(self):
        factory = AgentFactory()
        spec = _basic_spec(
            output_schema={
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["items"],
            }
        )
        agent = factory.spawn(spec, model=TestModel())
        fields = agent.output_type.model_fields
        assert "items" in fields

    def test_spawn_with_constraints(self):
        factory = AgentFactory()
        spec = _basic_spec(constraints=["Be concise", "No jargon"])
        agent = factory.spawn(spec, model=TestModel())
        assert "Constraints (you MUST follow these):" in agent.system_prompt
        assert "- Be concise" in agent.system_prompt
        assert "- No jargon" in agent.system_prompt

    def test_spawn_with_tools_from_registry(self):
        registry = ToolRegistry()
        tool = _make_tool("search")
        registry.register(tool, description="Search")
        factory = AgentFactory(registry=registry)
        spec = _basic_spec(
            tools=[ToolSpec(name="search", description="Search", source="registry")]
        )
        agent = factory.spawn(spec, model=TestModel())
        assert len(agent.tools) == 1
        assert agent.tools[0].name == "search"

    def test_spawn_missing_registry_tool_skipped(self):
        registry = ToolRegistry()
        factory = AgentFactory(registry=registry)
        spec = _basic_spec(
            tools=[ToolSpec(name="nonexistent", description="Missing")]
        )
        agent = factory.spawn(spec, model=TestModel())
        assert len(agent.tools) == 0

    @pytest.mark.asyncio
    async def test_dynamic_agent_run_implementation(self):
        factory = AgentFactory()
        spec = _basic_spec()
        agent = factory.spawn(spec, model=TestModel())
        state = GlobalState()
        state.add_message("user", "What is 2+2?")
        result = await agent.run(state)
        assert isinstance(result, BaseModel)
        assert hasattr(result, "answer")

    def test_schema_to_model_required_and_optional(self):
        factory = AgentFactory()
        schema = {
            "properties": {
                "required_field": {"type": "string", "description": "Must provide"},
                "optional_field": {
                    "type": "integer",
                    "description": "Can skip",
                    "default": 42,
                },
            },
            "required": ["required_field"],
        }
        model_cls = factory._schema_to_model("test", schema)
        fields = model_cls.model_fields
        assert fields["required_field"].is_required()
        assert not fields["optional_field"].is_required()
        assert fields["optional_field"].default == 42
