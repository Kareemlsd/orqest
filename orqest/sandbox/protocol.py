"""Sandbox Protocol + shared exceptions and result types.

The Protocol defines a two-stage contract — validate then execute — that
every sandbox backend must honor:

* :meth:`Sandbox.validate` performs static AST checks against the supplied
  code and the allowed-imports set. Raises :class:`ValidationError` on
  failure; returns ``None`` on success. Validation MUST be safe to call
  in any context (it doesn't execute the code).
* :meth:`Sandbox.execute` runs the pre-validated code with the supplied
  args and ALWAYS returns an :class:`ExecutionResult` — never raises for
  user-code failures (those land in :attr:`ExecutionResult.error`).
  Execute MAY re-validate (defense in depth — :class:`SubprocessSandbox`
  does this both at the parent and inside the child).

Two backends ship in this subpackage; third parties (or future waves)
can add :class:`E2BSandbox` / :class:`DockerSandbox` / :class:`WasmSandbox`
against this same Protocol.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ValidationError(Exception):
    """Raised by :meth:`Sandbox.validate` when static checks fail.

    Examples: a disallowed import, a syntax error, an explicit ``eval``
    call, or dunder attribute access (``obj.__class__``).
    """

    def __init__(self, reason: str, *, code_snippet: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code_snippet = code_snippet

    def __str__(self) -> str:
        return self.reason


class ExecutionResult(BaseModel):
    """Outcome of one :meth:`Sandbox.execute` call.

    Always emitted regardless of success — :class:`Sandbox` implementations
    MUST NOT raise for user-code failures (those land in :attr:`error`).
    Reserved for *infrastructure* failures (e.g., subprocess crash before
    handshake completes) which still raise from :meth:`Sandbox.execute`.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    """``True`` when the implementation ran to completion and returned a
    value without raising. ``False`` for any user-code exception, timeout,
    memory cap, or non-JSON-serializable return."""

    output: Any = None
    """JSON-serializable value the implementation returned. ``None`` on
    failure or when the implementation explicitly returned ``None``."""

    error: str | None = None
    """Captured exception message (or timeout / memory-cap signal) when
    :attr:`success` is False. ``None`` on success."""

    stdout: str = ""
    """Captured ``stdout`` from the implementation. Useful for debugging
    LLM-generated code that prints intermediate values."""

    duration_ms: float = Field(ge=0.0)
    """Wall-clock time spent inside the sandbox boundary."""


@runtime_checkable
class Sandbox(Protocol):
    """Protocol for safe execution of dynamic tool implementations.

    Two-stage contract — see module docstring. Implementations are async
    so they can do off-thread / off-process work (subprocess calls, HTTP
    to a sandbox provider, etc.) without blocking the agent loop.
    """

    async def validate(
        self,
        code: str,
        *,
        allowed_imports: set[str],
    ) -> None:
        """Static AST check. Raises :class:`ValidationError` on failure."""
        ...

    async def execute(
        self,
        code: str,
        *,
        args: dict[str, Any],
        allowed_imports: set[str],
        timeout_s: float = 5.0,
        memory_mb: int = 128,
        agent_id: str | None = None,
        dependencies: list[str] | None = None,
    ) -> ExecutionResult:
        """Run the (pre-validated) code with *args* and return the result.

        Always returns :class:`ExecutionResult`; ``success=False`` captures
        user-code failures, timeouts, memory caps, or unserializable output.
        Infrastructure failures (subprocess crash before handshake) still
        raise.

        Args:
            code: The implementation source.
            args: Per-call arguments passed to the implementation as ``args``.
            allowed_imports: Static-validation allowlist of top-level modules
                permitted in ``code``.
            timeout_s: Wall-clock cap inside the sandbox.
            memory_mb: Memory cap (enforced by Tier-1+; Tier-0 ignores).
            agent_id: Optional agent identifier — Tier-2 (Docker) routes
                execution into the agent's per-agent subfolder + ``.venv``.
                Tier-0 / Tier-1 ignore.
            dependencies: Optional list of pip specifiers (e.g.
                ``["pandas>=2.0"]``). Tier-2 installs them into the agent's
                ``.venv`` before executing (gated by ``allowed_packages``
                on the sandbox). Tier-0 / Tier-1 ignore.

        """
        ...

    async def __aenter__(self) -> Sandbox:
        """Optional context-manager hook for backends that hold resources."""
        ...

    async def __aexit__(self, *args: Any) -> None:
        """Optional context-manager teardown."""
        ...


__all__ = [
    "ExecutionResult",
    "Sandbox",
    "ValidationError",
]
