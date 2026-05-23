"""Tests for orqest.sandbox.protocol — Protocol shape + result types."""

from __future__ import annotations

import pytest

from orqest.sandbox import (
    ExecutionResult,
    InProcessSandbox,
    Sandbox,
    SubprocessSandbox,
    ValidationError,
)


def test_validation_error_carries_reason():
    exc = ValidationError("bad import", code_snippet="import os")
    assert exc.reason == "bad import"
    assert exc.code_snippet == "import os"
    assert str(exc) == "bad import"


def test_validation_error_default_code_snippet():
    exc = ValidationError("oops")
    assert exc.code_snippet == ""


def test_execution_result_shape():
    result = ExecutionResult(success=True, output={"x": 1}, duration_ms=12.5)
    assert result.success is True
    assert result.output == {"x": 1}
    assert result.error is None
    assert result.stdout == ""
    assert result.duration_ms == 12.5


def test_execution_result_failure_shape():
    result = ExecutionResult(
        success=False,
        error="boom",
        stdout="partial output\n",
        duration_ms=5.0,
    )
    assert result.success is False
    assert result.error == "boom"
    assert result.stdout == "partial output\n"


def test_inprocess_satisfies_protocol():
    sb = InProcessSandbox(unsafe=True)
    assert isinstance(sb, Sandbox)


def test_subprocess_satisfies_protocol():
    sb = SubprocessSandbox()
    assert isinstance(sb, Sandbox)


def test_execution_result_rejects_negative_duration():
    from pydantic import ValidationError as PydValidationError

    with pytest.raises(PydValidationError):
        ExecutionResult(success=True, duration_ms=-1.0)
