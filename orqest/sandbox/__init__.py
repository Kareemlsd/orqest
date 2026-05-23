"""``orqest.sandbox`` — safe execution of dynamic tool implementations.

The Protocol is small and explicit: validate then execute.

Two backends ship today:

* :class:`InProcessSandbox` — Tier 0; in-process ``exec()`` with AST-level
  static restriction. **Requires explicit** ``unsafe=True`` **at construction**
  because there is no real isolation. Suitable for tests and tightly-controlled
  dev workflows. NOT for LLM-generated code from untrusted sources.
* :class:`SubprocessSandbox` — Tier 1, the production default. Subprocess
  isolation with ``RLIMIT_AS`` + ``RLIMIT_CPU`` (POSIX) + outer
  ``asyncio.wait_for`` timeout. JSON args/result; stdin/stdout transport.

Third parties can ship :class:`E2BSandbox` / :class:`DockerSandbox` /
:class:`WasmSandbox` / :class:`FirecrackerSandbox` against the same
:class:`Sandbox` Protocol — see ``.claude/ARCHITECTURE.md`` §2.8.

The matching consumer is :class:`orqest.autonomy.tool_factory.DynamicToolFactory`,
which turns a :class:`GeneratedToolSpec` (carrying an ``implementation`` string)
into a runnable ``pydantic_ai.Tool`` via this Protocol.
"""

from orqest.sandbox.helpers import (
    SandboxRunError,
    run_in_sandbox,
    run_in_sandbox_safe,
)
from orqest.sandbox.inprocess import InProcessSandbox
from orqest.sandbox.protocol import ExecutionResult, Sandbox, ValidationError
from orqest.sandbox.subprocess import SubprocessSandbox

__all__ = [
    "ExecutionResult",
    "InProcessSandbox",
    "Sandbox",
    "SandboxRunError",
    "SubprocessSandbox",
    "ValidationError",
    "run_in_sandbox",
    "run_in_sandbox_safe",
]
