"""Tests for orqest.sandbox.subprocess.SubprocessSandbox.

Subprocess tests are slower than in-process (subprocess startup ~50ms each),
so this file runs ~10 tests covering the contract surface, not exhaustive
permutations. The validate-layer tests (shared with in-process) live in
test_inprocess.py.
"""

from __future__ import annotations

import pytest

from orqest.sandbox import SubprocessSandbox, ValidationError


@pytest.fixture
def sb():
    return SubprocessSandbox()


# --- validate (shared logic — covered by static tests) ----------------------


@pytest.mark.asyncio
async def test_validate_accepts_safe(sb):
    await sb.validate("return args['x']", allowed_imports=set())


@pytest.mark.asyncio
async def test_validate_rejects_unallowed_import(sb):
    with pytest.raises(ValidationError):
        await sb.validate("import os", allowed_imports=set())


# --- execute happy path ----------------------------------------------------


@pytest.mark.asyncio
async def test_execute_safe_arithmetic(sb):
    result = await sb.execute(
        "return args['a'] * args['b']",
        args={"a": 6, "b": 7},
        allowed_imports=set(),
    )
    assert result.success is True
    assert result.output == 42
    assert result.duration_ms > 0  # subprocess startup is non-zero


@pytest.mark.asyncio
async def test_execute_with_allowed_import(sb):
    code = "import re\nreturn re.findall(r'\\d+', args['text'])"
    result = await sb.execute(
        code, args={"text": "a1 b22 c333"}, allowed_imports={"re"}
    )
    assert result.success is True
    assert result.output == ["1", "22", "333"]


@pytest.mark.asyncio
async def test_execute_captures_user_exception(sb):
    result = await sb.execute(
        "raise ValueError('boom')",
        args={},
        allowed_imports=set(),
    )
    assert result.success is False
    assert "ValueError" in result.error
    assert "boom" in result.error


@pytest.mark.asyncio
async def test_execute_captures_stdout(sb):
    result = await sb.execute(
        "print('intermediate'); return 1",
        args={},
        allowed_imports=set(),
    )
    assert result.success is True
    assert "intermediate" in result.stdout


# --- execute timeout / resource caps ---------------------------------------


@pytest.mark.asyncio
async def test_execute_timeout_kills_subprocess(sb):
    result = await sb.execute(
        "while True: pass",
        args={},
        allowed_imports=set(),
        timeout_s=1.0,
    )
    assert result.success is False
    assert "timed out" in result.error
    assert result.duration_ms >= 1000  # at least the timeout


@pytest.mark.asyncio
async def test_execute_rejects_non_json_serializable(sb):
    result = await sb.execute(
        "return {1, 2}",  # set is not JSON-serializable
        args={},
        allowed_imports=set(),
    )
    assert result.success is False
    assert "JSON-serializable" in result.error


# --- defense in depth ------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_revalidates_inside_subprocess(sb):
    """Even if the parent's validate accepted by mistake (it shouldn't),
    the subprocess re-validates and refuses."""
    with pytest.raises(ValidationError):
        await sb.execute(
            "import os; return 1",
            args={},
            allowed_imports=set(),
        )


# --- concurrency -----------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_concurrent_calls_dont_interfere(sb):
    import asyncio

    code = "return args['x'] * 2"
    results = await asyncio.gather(
        sb.execute(code, args={"x": 1}, allowed_imports=set()),
        sb.execute(code, args={"x": 2}, allowed_imports=set()),
        sb.execute(code, args={"x": 3}, allowed_imports=set()),
    )
    outputs = sorted(r.output for r in results)
    assert outputs == [2, 4, 6]
    assert all(r.success for r in results)
