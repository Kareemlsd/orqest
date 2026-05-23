"""Tests for orqest.sandbox.inprocess.InProcessSandbox."""

from __future__ import annotations

import pytest

from orqest.sandbox import InProcessSandbox, ValidationError


# --- Construction -----------------------------------------------------------


class TestConstruction:
    def test_refuses_without_unsafe_kwarg(self):
        with pytest.raises(ValueError, match="unsafe=True"):
            InProcessSandbox()

    def test_refuses_with_unsafe_false(self):
        with pytest.raises(ValueError, match="unsafe=True"):
            InProcessSandbox(unsafe=False)

    def test_accepts_unsafe_true(self):
        sb = InProcessSandbox(unsafe=True)
        assert sb is not None


# --- validate ---------------------------------------------------------------


@pytest.fixture
def sb():
    return InProcessSandbox(unsafe=True)


@pytest.mark.asyncio
async def test_validate_accepts_safe_arithmetic(sb):
    await sb.validate("return args['x'] + 1", allowed_imports=set())


@pytest.mark.asyncio
async def test_validate_rejects_unallowed_import(sb):
    with pytest.raises(ValidationError, match="not in allowed_imports"):
        await sb.validate("import os; return 1", allowed_imports=set())


@pytest.mark.asyncio
async def test_validate_accepts_allowed_import(sb):
    await sb.validate("import re; return re.findall(r'\\d', '12')", allowed_imports={"re"})


@pytest.mark.asyncio
async def test_validate_rejects_eval(sb):
    with pytest.raises(ValidationError, match="forbidden name 'eval'"):
        await sb.validate("return eval('1+1')", allowed_imports=set())


@pytest.mark.asyncio
async def test_validate_rejects_exec(sb):
    with pytest.raises(ValidationError, match="forbidden name 'exec'"):
        await sb.validate("exec('x = 1'); return 1", allowed_imports=set())


@pytest.mark.asyncio
async def test_validate_rejects_dunder_subclasses(sb):
    with pytest.raises(ValidationError, match="forbidden attribute"):
        await sb.validate(
            "return ().__class__.__bases__[0].__subclasses__()",
            allowed_imports=set(),
        )


@pytest.mark.asyncio
async def test_validate_rejects_syntax_error(sb):
    with pytest.raises(ValidationError, match="syntax error"):
        await sb.validate("def +", allowed_imports=set())


# --- execute ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_safe_arithmetic(sb):
    result = await sb.execute("return args['x'] + args['y']", args={"x": 3, "y": 4}, allowed_imports=set())
    assert result.success is True
    assert result.output == 7
    assert result.error is None


@pytest.mark.asyncio
async def test_execute_with_allowed_import(sb):
    code = "import re; return re.findall(r'\\d+', args['text'])"
    result = await sb.execute(code, args={"text": "abc 12 def 34"}, allowed_imports={"re"})
    assert result.success is True
    assert result.output == ["12", "34"]


@pytest.mark.asyncio
async def test_execute_captures_exception(sb):
    code = "raise ValueError('user code error')"
    result = await sb.execute(code, args={}, allowed_imports=set())
    assert result.success is False
    assert "ValueError" in result.error
    assert "user code error" in result.error


@pytest.mark.asyncio
async def test_execute_captures_stdout(sb):
    code = "print('hello'); return 42"
    result = await sb.execute(code, args={}, allowed_imports=set())
    assert result.success is True
    assert result.output == 42
    assert "hello" in result.stdout


@pytest.mark.asyncio
async def test_execute_rejects_non_json_serializable_output(sb):
    code = "return {1, 2, 3}"  # set is not JSON-serializable
    result = await sb.execute(code, args={}, allowed_imports=set())
    assert result.success is False
    assert "JSON-serializable" in result.error


@pytest.mark.asyncio
async def test_execute_runs_validate_again_on_call(sb):
    # Even though caller didn't validate first, execute() validates internally
    with pytest.raises(ValidationError):
        await sb.execute("import socket", args={}, allowed_imports=set())


@pytest.mark.asyncio
async def test_execute_reports_unavailable_allowed_import(sb):
    code = "return 1"
    result = await sb.execute(code, args={}, allowed_imports={"definitely_not_a_real_module"})
    assert result.success is False
    assert "not available" in result.error
