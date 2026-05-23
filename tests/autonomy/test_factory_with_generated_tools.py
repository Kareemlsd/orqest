"""Tests for AgentFactory dispatching ToolSpec + GeneratedToolSpec."""

from __future__ import annotations

import pytest
from pydantic_ai import Tool
from pydantic_ai.models.test import TestModel

from orqest.autonomy.factory import AgentFactory
from orqest.autonomy.registry import ToolRegistry
from orqest.autonomy.spec import AgentSpec, GeneratedToolSpec, ToolSpec
from orqest.autonomy.tool_factory import DynamicToolFactory
from orqest.sandbox import InProcessSandbox


@pytest.fixture
def registry():
    reg = ToolRegistry()

    async def search(q: str) -> str:
        """Search the web."""
        return f"searched: {q}"

    reg.register(Tool(search, name="search"))
    return reg


@pytest.fixture
def tool_factory():
    return DynamicToolFactory(InProcessSandbox(unsafe=True))


@pytest.fixture
def output_schema():
    return {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }


def _spec_with_tools(tools, output_schema):
    return AgentSpec(
        name="agent",
        system_prompt="hi",
        output_schema=output_schema,
        tools=tools,
    )


# --- Mixed dispatch --------------------------------------------------------


def test_registered_only_tools_resolve(registry, output_schema):
    factory = AgentFactory(registry=registry)
    spec = _spec_with_tools([ToolSpec(name="search", description="x")], output_schema)
    agent = factory.spawn(spec, model=TestModel())
    assert [t.name for t in agent.tools] == ["search"]


def test_generated_only_tool_resolves(registry, tool_factory, output_schema):
    factory = AgentFactory(registry=registry, tool_factory=tool_factory)
    gts = GeneratedToolSpec(
        name="upper",
        description="Uppercase.",
        parameters={"text": {"type": "string"}},
        implementation="return args['text'].upper()",
        allowed_imports=set(),
    )
    spec = _spec_with_tools([gts], output_schema)
    agent = factory.spawn(spec, model=TestModel())
    assert [t.name for t in agent.tools] == ["upper"]


def test_mixed_tools_both_resolve(registry, tool_factory, output_schema):
    gts = GeneratedToolSpec(
        name="word_count",
        description="Count words.",
        parameters={"text": {"type": "string"}},
        implementation="return {'count': len(args['text'].split())}",
        allowed_imports=set(),
    )
    factory = AgentFactory(registry=registry, tool_factory=tool_factory)
    spec = _spec_with_tools(
        [ToolSpec(name="search", description="x"), gts], output_schema
    )
    agent = factory.spawn(spec, model=TestModel())
    names = sorted(t.name for t in agent.tools)
    assert names == ["search", "word_count"]


# --- Graceful degradation --------------------------------------------------


def test_generated_spec_without_tool_factory_logged_and_dropped(
    registry, output_schema, caplog
):
    factory = AgentFactory(registry=registry, tool_factory=None)
    gts = GeneratedToolSpec(
        name="missing",
        description="x",
        parameters={},
        implementation="return 1",
        allowed_imports=set(),
    )
    spec = _spec_with_tools([gts], output_schema)
    agent = factory.spawn(spec, model=TestModel())
    # No tool because tool_factory is missing
    assert agent.tools == []


def test_generated_spec_with_invalid_implementation_logged_and_dropped(
    registry, tool_factory, output_schema
):
    factory = AgentFactory(registry=registry, tool_factory=tool_factory)
    bad = GeneratedToolSpec(
        name="bad",
        description="x",
        parameters={},
        implementation="import os; return os.getcwd()",  # disallowed
        allowed_imports=set(),
    )
    spec = _spec_with_tools([bad], output_schema)
    agent = factory.spawn(spec, model=TestModel())
    # Spawn raises ValidationError internally; factory catches + drops
    assert agent.tools == []


def test_unknown_registered_name_dropped(registry, output_schema):
    factory = AgentFactory(registry=registry)
    spec = _spec_with_tools(
        [ToolSpec(name="ghost", description="x")], output_schema
    )
    agent = factory.spawn(spec, model=TestModel())
    assert agent.tools == []


# --- Spawned tool actually invokable inside the agent ---------------------


@pytest.mark.asyncio
async def test_spawned_tool_invocation(tool_factory, output_schema):
    """End-to-end: factory spawns the tool; we invoke its function directly."""
    gts = GeneratedToolSpec(
        name="double",
        description="Double a number.",
        parameters={"x": {"type": "integer"}},
        implementation="return args['x'] * 2",
        allowed_imports=set(),
    )
    factory = AgentFactory(tool_factory=tool_factory)
    spec = _spec_with_tools([gts], output_schema)
    agent = factory.spawn(spec, model=TestModel())
    assert len(agent.tools) == 1
    result = await agent.tools[0].function(x=21)
    assert result == 42
