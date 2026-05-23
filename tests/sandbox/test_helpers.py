"""Tests for the high-level :func:`run_in_sandbox` helper.

Pins the contract the helper exists to provide: collapse the 30-line
GeneratedToolSpec + DynamicToolFactory + invoke pattern into one call,
with clear errors on validation/execution failures.
"""

from __future__ import annotations

import pytest

from orqest.sandbox import (
    InProcessSandbox,
    SandboxRunError,
    SubprocessSandbox,
    run_in_sandbox,
    run_in_sandbox_safe,
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_in_sandbox_simple_call_returns_value():
    """The canonical case: define a function, call it via return_expression,
    get the value back."""
    code = "def add(a, b):\n    return a + b"
    result = await run_in_sandbox(
        code,
        return_expression="add(2, 3)",
    )
    assert result == 5


@pytest.mark.asyncio
async def test_run_in_sandbox_with_return_already_in_code():
    """When the code itself contains a top-level return, return_expression
    is optional. The wrapper just executes the body."""
    code = "x = 10\nreturn x * 2"
    result = await run_in_sandbox(code)
    assert result == 20


@pytest.mark.asyncio
async def test_run_in_sandbox_passes_args_dict():
    """args dict reaches the wrapper as `args` inside the candidate code."""
    code = "return args['key'] + 100"
    result = await run_in_sandbox(code, args={"key": 5})
    assert result == 105


@pytest.mark.asyncio
async def test_run_in_sandbox_with_allowed_imports():
    """Imports declared in allowed_imports survive AST validation."""
    code = "import re\ndef extract_nums(s):\n    return re.findall(r'\\d+', s)"
    result = await run_in_sandbox(
        code,
        return_expression="extract_nums('a1 b22 c333')",
        allowed_imports={"re"},
    )
    assert result == ["1", "22", "333"]


# ---------------------------------------------------------------------------
# Validation failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_in_sandbox_rejects_forbidden_exec_call():
    """Calling exec() (forbidden) raises SandboxRunError with stage='validate'."""
    code = "x = 1\nresult = exec('print(2)')\nreturn result"
    with pytest.raises(SandboxRunError) as excinfo:
        await run_in_sandbox(code)
    assert excinfo.value.stage == "validate"
    assert "exec" in str(excinfo.value)
    assert excinfo.value.code_snippet  # has a snippet


@pytest.mark.asyncio
async def test_run_in_sandbox_rejects_unauthorized_import():
    """Importing a module not in allowed_imports fails validation."""
    code = "import os\nreturn os.getcwd()"
    with pytest.raises(SandboxRunError) as excinfo:
        await run_in_sandbox(code)  # empty allowed_imports
    assert excinfo.value.stage == "validate"


# ---------------------------------------------------------------------------
# Execution failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_in_sandbox_raises_on_timeout():
    """A runaway loop hits the outer timeout and raises with stage='execute'."""
    code = "while True:\n    pass"
    with pytest.raises(SandboxRunError) as excinfo:
        await run_in_sandbox(code, timeout_s=0.5)
    assert excinfo.value.stage == "execute"


@pytest.mark.asyncio
async def test_run_in_sandbox_raises_on_runtime_error():
    """A candidate that raises at execution time surfaces as SandboxRunError."""
    code = "raise ValueError('boom')"
    with pytest.raises(SandboxRunError) as excinfo:
        await run_in_sandbox(code)
    assert excinfo.value.stage == "execute"


# ---------------------------------------------------------------------------
# Non-raising variant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_in_sandbox_safe_returns_success_tuple():
    """Successful run: tuple is (True, output, None)."""
    ok, output, err = await run_in_sandbox_safe(
        "def f(x):\n    return x * x",
        return_expression="f(7)",
    )
    assert ok is True
    assert output == 49
    assert err is None


@pytest.mark.asyncio
async def test_run_in_sandbox_safe_returns_failure_tuple_on_validation():
    """Validation failure: tuple is (False, None, message)."""
    ok, output, err = await run_in_sandbox_safe(
        "import socket\nreturn socket.gethostname()",
    )
    assert ok is False
    assert output is None
    assert err is not None
    assert "socket" in err or "import" in err


@pytest.mark.asyncio
async def test_run_in_sandbox_safe_returns_failure_tuple_on_timeout():
    """Timeout: tuple is (False, None, message)."""
    ok, output, err = await run_in_sandbox_safe(
        "while True:\n    pass", timeout_s=0.3
    )
    assert ok is False
    assert output is None
    assert err is not None


# ---------------------------------------------------------------------------
# Sandbox injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_in_sandbox_accepts_custom_sandbox():
    """The sandbox arg lets callers share lifecycle (e.g., reuse a single
    SubprocessSandbox across many calls)."""
    sandbox = SubprocessSandbox()
    result = await run_in_sandbox(
        "def f(): return 42",
        return_expression="f()",
        sandbox=sandbox,
    )
    assert result == 42


@pytest.mark.asyncio
async def test_run_in_sandbox_works_with_inprocess_sandbox():
    """InProcessSandbox (Tier 0) is wired through for tests/dev workflows."""
    sandbox = InProcessSandbox(unsafe=True)
    result = await run_in_sandbox(
        "return args['n'] + 1",
        args={"n": 9},
        sandbox=sandbox,
    )
    assert result == 10
