"""High-level helpers over the :mod:`orqest.sandbox` Protocol.

The canonical use case for ``orqest.sandbox`` is "run a candidate Python
function, get its return value back" — exercised heavily in test-driven
agent loops (notebook 12, ``benchmarks/coding/``). The raw Protocol
(:meth:`Sandbox.execute`) is the right abstraction for building agent-callable
tools (``GeneratedToolSpec`` + ``DynamicToolFactory``), but it requires
~30 lines per call site for the common shape:

  1. Wrap candidate code + ``return <expression>`` into an implementation string.
  2. Instantiate (or reuse) a sandbox backend.
  3. ``execute()`` with allowed-imports + timeout.
  4. Unwrap :class:`ExecutionResult` — success/failure/timeout handling.

:func:`run_in_sandbox` collapses that into one line. Two variants ship:

* :func:`run_in_sandbox` — raises :class:`SandboxRunError` on validation /
  execution failure. Suited for code that should bail loud (eg test harnesses).
* :func:`run_in_sandbox_safe` — returns ``(success, output, error)`` tuple.
  Suited for code that wants to handle failures inline without try/except.

Neither helper is a *replacement* for ``GeneratedToolSpec`` + ``DynamicToolFactory``
— those still apply when the agent itself needs to *call* a tool through
pydantic-ai's tool-use mechanism. These helpers are for *direct* invocation
from framework code outside the agent loop.
"""

from __future__ import annotations

from typing import Any

from orqest.sandbox.protocol import ExecutionResult, Sandbox, ValidationError
from orqest.sandbox.subprocess import SubprocessSandbox


class SandboxRunError(RuntimeError):
    """Raised by :func:`run_in_sandbox` on validation / execution failure.

    Attributes:
        stage: ``"validate"`` (AST rejected the code) or ``"execute"`` (sandbox
            launched the code but it errored / timed out / produced unparseable
            output).
        code_snippet: First ~200 chars of the offending implementation, for
            diagnostics.
        underlying: The raw :class:`ExecutionResult` (when ``stage="execute"``)
            or :class:`ValidationError` (when ``stage="validate"``) — for
            consumers who need the structured error fields.

    """

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        code_snippet: str,
        underlying: ExecutionResult | ValidationError | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.code_snippet = code_snippet
        self.underlying = underlying


def _build_implementation(code: str, return_expression: str | None) -> str:
    """Wrap user code so that it returns ``return_expression`` (when given)
    from the sandbox subprocess's wrapped function body.

    With ``return_expression="solve(7, 3)"``, an implementation like::

        def solve(a, b):
            return a + b
        return solve(7, 3)

    runs the candidate inside the sandbox and pushes its result back.
    Without ``return_expression``, the helper assumes ``code`` itself already
    contains a top-level ``return`` statement.
    """
    if return_expression is None:
        return code
    return f"{code}\nreturn {return_expression}\n"


async def run_in_sandbox(
    code: str,
    *,
    return_expression: str | None = None,
    args: dict[str, Any] | None = None,
    allowed_imports: set[str] | None = None,
    sandbox: Sandbox | None = None,
    timeout_s: float = 5.0,
    memory_mb: int = 128,
) -> Any:
    """Run *code* in a sandbox; return the value (or raise :class:`SandboxRunError`).

    Args:
        code: Python source — typically a function definition. The body runs
            inside an isolated ``def __orqest_tool(args)`` wrapper supplied
            by the sandbox.
        return_expression: When given, appended as ``\\nreturn {expr}\\n`` so
            the wrapper returns it. When ``None``, *code* must already
            include a top-level ``return`` statement.
        args: Dict passed as ``args`` into the wrapper. Default ``{}``.
        allowed_imports: Top-level module names the candidate may import.
            Default empty (any ``import`` statement in the candidate fails
            static validation).
        sandbox: An optional :class:`Sandbox` instance. Default is a fresh
            :class:`SubprocessSandbox` (Tier 1 — subprocess + RLIMIT caps +
            outer timeout). Pass an existing sandbox to share lifecycle.
        timeout_s: Wall-clock cap on execution. Default 5.0s.
        memory_mb: Memory cap in MB. Default 128.

    Returns:
        Whatever the wrapped function returns (JSON-serialisable values only,
        per the sandbox Protocol).

    Raises:
        SandboxRunError: Validation failure (``stage="validate"``) or
            execution failure / timeout (``stage="execute"``). The exception
            carries ``code_snippet`` and ``underlying`` for diagnostics.

    """
    sandbox = sandbox or SubprocessSandbox()
    implementation = _build_implementation(code, return_expression)
    snippet = implementation[:200]
    effective_imports = set(allowed_imports) if allowed_imports else set()
    effective_args = dict(args) if args else {}

    try:
        await sandbox.validate(implementation, allowed_imports=effective_imports)
    except ValidationError as exc:
        raise SandboxRunError(
            f"sandbox validation rejected the implementation: {exc}",
            stage="validate",
            code_snippet=snippet,
            underlying=exc,
        ) from exc

    result = await sandbox.execute(
        implementation,
        args=effective_args,
        allowed_imports=effective_imports,
        timeout_s=timeout_s,
        memory_mb=memory_mb,
    )

    if not result.success:
        raise SandboxRunError(
            f"sandbox execution failed: {result.error or 'unknown error'}",
            stage="execute",
            code_snippet=snippet,
            underlying=result,
        )

    return result.output


async def run_in_sandbox_safe(
    code: str,
    *,
    return_expression: str | None = None,
    args: dict[str, Any] | None = None,
    allowed_imports: set[str] | None = None,
    sandbox: Sandbox | None = None,
    timeout_s: float = 5.0,
    memory_mb: int = 128,
) -> tuple[bool, Any, str | None]:
    """Non-raising variant of :func:`run_in_sandbox`.

    Returns ``(success, output, error_message)``. On success: ``(True, result, None)``.
    On any failure (validation or execution): ``(False, None, <error_msg>)``.

    Suited for code that wants to handle failure inline without try/except —
    e.g., test-driven loops that iterate over many candidates and need a
    per-candidate verdict without exception bookkeeping.
    """
    try:
        output = await run_in_sandbox(
            code,
            return_expression=return_expression,
            args=args,
            allowed_imports=allowed_imports,
            sandbox=sandbox,
            timeout_s=timeout_s,
            memory_mb=memory_mb,
        )
    except SandboxRunError as exc:
        return False, None, str(exc)
    return True, output, None


__all__ = ["SandboxRunError", "run_in_sandbox", "run_in_sandbox_safe"]
