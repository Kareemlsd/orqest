"""Tests for AgentSpec and ToolSpec serialization and validation."""
from __future__ import annotations

from orqest.autonomy.spec import AgentSpec, ToolSpec


class TestToolSpec:
    def test_defaults(self):
        spec = ToolSpec(name="search", description="Search the web")
        assert spec.name == "search"
        assert spec.description == "Search the web"
        assert spec.parameters == {}

    def test_carries_parameter_schema(self):
        spec = ToolSpec(
            name="calc",
            description="Calculate",
            parameters={"type": "object", "properties": {"x": {"type": "number"}}},
        )
        assert spec.parameters["properties"]["x"]["type"] == "number"


class TestAgentSpec:
    def test_minimal_fields(self):
        spec = AgentSpec(
            name="summarizer",
            system_prompt="Summarize text.",
            output_schema={"properties": {"summary": {"type": "string"}}},
        )
        assert spec.name == "summarizer"
        assert spec.tools == []
        assert spec.model == "openai:gpt-4.1"
        assert spec.constraints == []

    def test_all_fields_populated(self):
        spec = AgentSpec(
            name="researcher",
            system_prompt="Research topics.",
            output_schema={
                "properties": {"findings": {"type": "string"}},
                "required": ["findings"],
            },
            tools=[ToolSpec(name="search", description="Web search")],
            model="anthropic:claude-sonnet-4-20250514",
            constraints=["No personal data", "Max 500 words"],
        )
        assert spec.name == "researcher"
        assert len(spec.tools) == 1
        assert spec.model == "anthropic:claude-sonnet-4-20250514"
        assert len(spec.constraints) == 2

    def test_serialization_round_trip(self):
        spec = AgentSpec(
            name="writer",
            system_prompt="Write prose.",
            output_schema={
                "properties": {
                    "text": {"type": "string"},
                    "word_count": {"type": "integer"},
                },
                "required": ["text"],
            },
            tools=[ToolSpec(name="grammar", description="Check grammar")],
            constraints=["Formal tone"],
        )
        json_str = spec.model_dump_json()
        restored = AgentSpec.model_validate_json(json_str)
        assert restored == spec

    def test_constraints_are_list_of_strings(self):
        spec = AgentSpec(
            name="safe_agent",
            system_prompt="Be safe.",
            output_schema={"properties": {}},
            constraints=["Rule 1", "Rule 2", "Rule 3"],
        )
        assert isinstance(spec.constraints, list)
        assert all(isinstance(c, str) for c in spec.constraints)
        assert len(spec.constraints) == 3
