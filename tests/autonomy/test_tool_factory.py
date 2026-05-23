"""Tests for orqest.autonomy.tool_factory.DynamicToolFactory."""

from __future__ import annotations

from typing import Any

import pytest

from orqest.autonomy.spec import GeneratedToolSpec
from orqest.autonomy.tool_factory import DynamicToolFactory
from orqest.observability.events import EventBus
from orqest.sandbox import InProcessSandbox, ValidationError


@pytest.fixture
def sandbox():
    return InProcessSandbox(unsafe=True)


@pytest.fixture
def factory(sandbox):
    return DynamicToolFactory(sandbox)


def _spec(
    name: str = "tool",
    impl: str = "return args.get('x', 0) * 2",
    allowed: set[str] | None = None,
) -> GeneratedToolSpec:
    return GeneratedToolSpec(
        name=name,
        description=f"{name} description",
        parameters={"x": {"type": "integer"}},
        implementation=impl,
        allowed_imports=allowed or set(),
    )


# --- Construction -----------------------------------------------------------


def test_factory_holds_sandbox(sandbox):
    f = DynamicToolFactory(sandbox)
    assert f.sandbox is sandbox


def test_factory_default_timeout_memory(sandbox):
    f = DynamicToolFactory(sandbox, default_timeout_s=2.5, default_memory_mb=64)
    assert f._default_timeout_s == 2.5
    assert f._default_memory_mb == 64


# --- spawn happy path ------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_returns_pydantic_ai_tool(factory):
    from pydantic_ai import Tool

    tool = await factory.spawn(_spec())
    assert isinstance(tool, Tool)
    assert tool.name == "tool"
    assert tool.description == "tool description"


@pytest.mark.asyncio
async def test_spawned_tool_invocation_returns_output(factory):
    tool = await factory.spawn(_spec())
    result = await tool.function(x=5)
    assert result == 10


@pytest.mark.asyncio
async def test_spawned_tool_with_allowed_import(factory):
    spec = _spec(
        impl="import re; return {'matches': re.findall(r'\\d+', args['text'])}",
        allowed={"re"},
    )
    spec = GeneratedToolSpec(
        name="finder",
        description="find numbers",
        parameters={"text": {"type": "string"}},
        implementation="import re\nreturn {'matches': re.findall(r'\\d+', args['text'])}",
        allowed_imports={"re"},
    )
    tool = await factory.spawn(spec)
    result = await tool.function(text="a1b22c")
    assert result == {"matches": ["1", "22"]}


# --- spawn validation failures --------------------------------------------


@pytest.mark.asyncio
async def test_spawn_rejects_disallowed_import(factory):
    spec = _spec(impl="import os; return os.getcwd()")
    with pytest.raises(ValidationError, match="not in allowed_imports"):
        await factory.spawn(spec)


@pytest.mark.asyncio
async def test_spawn_rejects_eval(factory):
    spec = _spec(impl="return eval(args['expr'])")
    with pytest.raises(ValidationError, match="forbidden name 'eval'"):
        await factory.spawn(spec)


@pytest.mark.asyncio
async def test_spawn_rejects_dunder_subclasses(factory):
    spec = _spec(impl="return ().__class__.__bases__")
    with pytest.raises(ValidationError, match="forbidden attribute"):
        await factory.spawn(spec)


# --- runtime failure handling ---------------------------------------------


@pytest.mark.asyncio
async def test_invocation_failure_returns_structured_error(factory):
    spec = _spec(impl="raise ValueError('boom')")
    tool = await factory.spawn(spec)
    result = await tool.function()
    # Structured error dict, NOT a Python exception (so the LLM loop sees it)
    assert isinstance(result, dict)
    assert "error" in result
    assert "ValueError" in result["error"]
    assert result["stage"] == "sandbox.execute"
    assert result["tool_name"] == "tool"


# --- bus events ------------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_emits_tool_spawned(sandbox):
    bus = EventBus()
    received: list[Any] = []
    bus.subscribe("tool.spawned", received.append)

    factory = DynamicToolFactory(sandbox, bus=bus)
    await factory.spawn(_spec())

    import asyncio

    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].data["tool_name"] == "tool"


@pytest.mark.asyncio
async def test_bus_emits_validation_rejected(sandbox):
    bus = EventBus()
    received: list[Any] = []
    bus.subscribe("sandbox.validation_rejected", received.append)
    bus.subscribe("tool.spawn_failed", received.append)

    factory = DynamicToolFactory(sandbox, bus=bus)
    with pytest.raises(ValidationError):
        await factory.spawn(_spec(impl="import os"))

    import asyncio

    await asyncio.sleep(0.05)
    types = {e.event_type for e in received}
    assert "sandbox.validation_rejected" in types
    assert "tool.spawn_failed" in types


@pytest.mark.asyncio
async def test_bus_emits_invocation_completed(sandbox):
    bus = EventBus()
    received: list[Any] = []
    bus.subscribe("tool.invocation_completed", received.append)

    factory = DynamicToolFactory(sandbox, bus=bus)
    tool = await factory.spawn(_spec())
    await tool.function(x=3)

    import asyncio

    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].data["tool_name"] == "tool"


# --- per-spec overrides ----------------------------------------------------


@pytest.mark.asyncio
async def test_spec_timeout_propagates_to_sandbox(factory):
    """A spec with a tight timeout cap should propagate to sandbox.execute."""
    # InProcessSandbox accepts but doesn't enforce timeout, so we just verify
    # it doesn't break the call. SubprocessSandbox tests cover real enforcement.
    spec = GeneratedToolSpec(
        name="quick",
        description="quick tool",
        parameters={},
        implementation="return 1",
        allowed_imports=set(),
        timeout_s=0.5,
    )
    tool = await factory.spawn(spec)
    result = await tool.function()
    assert result == 1


@pytest.mark.asyncio
async def test_multiple_spawns_independent(factory):
    spec_a = _spec(name="a", impl="return 'a'")
    spec_b = _spec(name="b", impl="return 'b'")
    tool_a = await factory.spawn(spec_a)
    tool_b = await factory.spawn(spec_b)
    assert tool_a.name == "a"
    assert tool_b.name == "b"
    assert (await tool_a.function()) == "a"
    assert (await tool_b.function()) == "b"
