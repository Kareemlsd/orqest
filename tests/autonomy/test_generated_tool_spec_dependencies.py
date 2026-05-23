"""Tests for the new GeneratedToolSpec.dependencies field."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Tool

from orqest.autonomy.spec import GeneratedToolSpec
from orqest.autonomy.tool_factory import DynamicToolFactory
from orqest.sandbox import InProcessSandbox
from orqest.sandbox.protocol import ExecutionResult


def test_dependencies_field_default_empty():
    spec = GeneratedToolSpec(
        name="x",
        description="x",
        parameters={},
        implementation="return 1",
        allowed_imports=set(),
    )
    assert spec.dependencies == []


def test_dependencies_field_round_trips():
    spec = GeneratedToolSpec(
        name="x",
        description="x",
        parameters={},
        implementation="return 1",
        allowed_imports={"pandas"},
        dependencies=["pandas>=2.0", "numpy"],
    )
    assert spec.dependencies == ["pandas>=2.0", "numpy"]
    # JSON round-trip
    restored = GeneratedToolSpec.model_validate_json(spec.model_dump_json())
    assert restored.dependencies == ["pandas>=2.0", "numpy"]


@pytest.mark.asyncio
async def test_dependencies_forwarded_to_sandbox_execute():
    """Verify the runner closure passes spec.dependencies to sandbox.execute."""

    class _CapturingSandbox:
        captured: dict[str, Any] = {}

        async def validate(self, code: str, *, allowed_imports: set[str]) -> None:
            return None

        async def execute(
            self, code: str, *, args, allowed_imports, timeout_s, memory_mb,
            agent_id=None, dependencies=None,
        ) -> ExecutionResult:
            self.captured["agent_id"] = agent_id
            self.captured["dependencies"] = dependencies
            return ExecutionResult(success=True, output=42, duration_ms=1.0)

    sandbox = _CapturingSandbox()
    factory = DynamicToolFactory(sandbox)
    spec = GeneratedToolSpec(
        name="x", description="x", parameters={},
        implementation="return 1", allowed_imports=set(),
        dependencies=["httpx>=0.27"],
    )
    tool = await factory.spawn(spec, agent_id="alice")
    await tool.function()
    assert sandbox.captured["agent_id"] == "alice"
    assert sandbox.captured["dependencies"] == ["httpx>=0.27"]


@pytest.mark.asyncio
async def test_empty_dependencies_passes_none_to_sandbox():
    """When spec.dependencies is empty, the runner passes None — keeps the
    Tier-0/1 sandboxes happy (they don't iterate dependencies)."""
    captured: dict[str, Any] = {}

    class _CapturingSandbox:
        async def validate(self, code, *, allowed_imports):
            return None

        async def execute(self, code, *, args, allowed_imports, timeout_s,
                          memory_mb, agent_id=None, dependencies=None):
            captured["dependencies"] = dependencies
            return ExecutionResult(success=True, output=1, duration_ms=1.0)

    spec = GeneratedToolSpec(
        name="x", description="x", parameters={},
        implementation="return 1", allowed_imports=set(),
    )
    tool = await DynamicToolFactory(_CapturingSandbox()).spawn(spec)
    await tool.function()
    assert captured["dependencies"] is None


@pytest.mark.asyncio
async def test_inprocess_sandbox_ignores_dependencies():
    """Tier-0 sandbox accepts but ignores the dependencies kwarg — Protocol conformance."""
    sb = InProcessSandbox(unsafe=True)
    result = await sb.execute(
        "return args['x']",
        args={"x": 7},
        allowed_imports=set(),
        agent_id="alice",
        dependencies=["this", "would", "be", "ignored"],
    )
    assert result.success is True
    assert result.output == 7
