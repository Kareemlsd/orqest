"""Tier-0 sandbox — in-process exec() with AST-level static restriction.

**This is not real isolation.** A determined attacker can still:

* Hang the event loop (no thread / process boundary)
* Allocate unbounded memory (no resource limits)
* Reach restricted-but-not-deleted functions via class-introspection tricks
  (``().__class__.__bases__[0].__subclasses__()`` etc. — the static
  validator catches dunder access, but the attack surface is wide)

Use :class:`InProcessSandbox` only for tests + tightly-controlled dev
workflows. For anything that runs LLM-generated code from an untrusted
source, use :class:`SubprocessSandbox` (or a third-party
:class:`E2BSandbox` / :class:`DockerSandbox` future seam).

Constructor refuses ``unsafe=False`` — opt-in is the API.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from time import monotonic
from typing import Any, ClassVar

from orqest.sandbox._static import collect_issues, format_issues
from orqest.sandbox.protocol import ExecutionResult, ValidationError


class InProcessSandbox:
    """Tier-0 sandbox — see module docstring. Refuses ``unsafe=False``."""

    _SAFE_BUILTINS: ClassVar[dict[str, Any]] = {
        # Arithmetic + safe collection helpers + str/repr.
        # NOTABLY ABSENT: __import__, eval, exec, open, compile, globals,
        # locals, vars, input, breakpoint, exit, quit, help.
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "bytes": bytes,
        "chr": chr,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "frozenset": frozenset,
        "hash": hash,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "iter": iter,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "oct": oct,
        "ord": ord,
        "pow": pow,
        "print": print,  # captured via redirect_stdout
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        # Common exceptions so user code can catch / raise them.
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "RuntimeError": RuntimeError,
    }

    def __init__(self, *, unsafe: bool = False) -> None:
        if not unsafe:
            raise ValueError(
                "InProcessSandbox requires unsafe=True — there is no real "
                "isolation. Use SubprocessSandbox for production. See the "
                "module docstring for what InProcessSandbox does NOT protect."
            )
        self._unsafe = unsafe

    async def validate(
        self,
        code: str,
        *,
        allowed_imports: set[str],
    ) -> None:
        """Static AST check; raise :class:`ValidationError` on issues."""
        issues = collect_issues(code, allowed_imports=allowed_imports)
        if issues:
            raise ValidationError(
                format_issues(issues),
                code_snippet=code[:200],
            )

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
        """Validate, then run the code in a restricted namespace.

        Note that ``timeout_s``, ``memory_mb``, ``agent_id``, and
        ``dependencies`` are accepted for Protocol conformance but
        **not enforced** by this backend — the in-process path has no
        process boundary to enforce them on, and there are no per-agent
        venvs in-process.
        """
        # Re-validate (defense in depth — also done at spawn time)
        await self.validate(code, allowed_imports=allowed_imports)

        # Build the restricted namespace. Pre-bind allowed-import modules so
        # user code sees them already in scope; also install a restricted
        # __import__ so user code that writes `import re` (a common LLM
        # pattern) works without triggering the default __import__ machinery.
        # The restricted import only allows modules in allowed_imports.
        import importlib

        builtins = dict(self._SAFE_BUILTINS)

        def _restricted_import(
            name: str,
            globals: dict | None = None,
            locals: dict | None = None,
            fromlist: tuple = (),
            level: int = 0,
        ) -> Any:
            root = name.split(".", 1)[0]
            if root not in allowed_imports:
                raise ImportError(
                    f"import of {name!r} blocked by sandbox; allowed: {sorted(allowed_imports)}"
                )
            return importlib.import_module(name)

        builtins["__import__"] = _restricted_import

        namespace: dict[str, Any] = {
            "__builtins__": builtins,
            "args": dict(args),
        }
        for module_name in allowed_imports:
            try:
                namespace[module_name.split(".", 1)[0]] = importlib.import_module(
                    module_name
                )
            except ImportError as exc:
                return ExecutionResult(
                    success=False,
                    error=f"allowed import {module_name!r} not available: {exc}",
                    duration_ms=0.0,
                )

        # User code is wrapped in a function so its `return` becomes the
        # captured output. The wrapper assigns the return value to a
        # well-known name (``__orqest_result``) we can read after exec.
        wrapped = (
            "def __orqest_tool(args):\n"
            + "\n".join("    " + line for line in code.splitlines())
            + "\n__orqest_result = __orqest_tool(args)\n"
        )

        stdout_buf = io.StringIO()
        t0 = monotonic()
        try:
            with redirect_stdout(stdout_buf):
                # ruff: noqa: S102  (sandbox is the whole point)
                exec(wrapped, namespace)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                stdout=stdout_buf.getvalue(),
                duration_ms=(monotonic() - t0) * 1000.0,
            )

        result = namespace.get("__orqest_result")
        # JSON-roundtrip the result to enforce serializability (matches
        # the SubprocessSandbox boundary so behaviour is identical).
        try:
            json.dumps(result)
        except (TypeError, ValueError) as exc:
            return ExecutionResult(
                success=False,
                error=f"return value is not JSON-serializable: {exc}",
                stdout=stdout_buf.getvalue(),
                duration_ms=(monotonic() - t0) * 1000.0,
            )

        return ExecutionResult(
            success=True,
            output=result,
            stdout=stdout_buf.getvalue(),
            duration_ms=(monotonic() - t0) * 1000.0,
        )

    async def __aenter__(self) -> InProcessSandbox:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None


__all__ = ["InProcessSandbox"]
