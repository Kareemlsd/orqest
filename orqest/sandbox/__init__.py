"""``orqest.sandbox`` — safe execution of dynamic tool implementations.

The Protocol is small and explicit: validate then execute.

Three backends ship today:

* :class:`InProcessSandbox` — Tier 0; in-process ``exec()`` with AST-level
  static restriction and a curated ``__builtins__`` set. **Requires explicit**
  ``unsafe=True`` **at construction** because there is no real isolation.
  Suitable for tests and tightly-controlled dev workflows. NOT for
  LLM-generated code from untrusted sources.
* :class:`SubprocessSandbox` — Tier 1, the production default. Subprocess
  isolation with ``RLIMIT_AS`` + ``RLIMIT_CPU`` (POSIX) + outer
  ``asyncio.wait_for`` timeout. The wrapper subprocess runs against the same
  curated ``__builtins__`` (from :mod:`orqest.sandbox._safe_builtins`) so
  reflection helpers and the unsafe builtins are never reachable. JSON
  args/result; stdin/stdout transport.
* :class:`orqest.sandbox.docker.DockerSandbox` — Tier 2; per-session
  container running the published ``orqest/agent-runtime`` image. Requires
  ``uv sync --group docker``. Imported lazily from the ``orqest.sandbox.docker``
  submodule so the host-side ``docker`` SDK stays an optional dep. Adds
  scope-separated JWT auth (``agent`` for execution, ``operator`` for
  ``promote_tool`` / ``forget_tool``) and per-user persisted tool library.

Every tier rejects the same set of static escapes (default-deny imports,
reflection helpers, dunder reach-through, string-keyed subscript access —
see :mod:`orqest.sandbox._static`) and runs with the same curated
``__builtins__`` (:mod:`orqest.sandbox._safe_builtins`). Identifier paths
that feed into per-agent workspaces are bounded by
:mod:`orqest.sandbox._identifiers`.

Third parties can ship :class:`E2BSandbox` / :class:`WasmSandbox` /
:class:`FirecrackerSandbox` against the same :class:`Sandbox` Protocol —
no changes required in core.

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
