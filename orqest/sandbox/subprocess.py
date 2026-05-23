"""Tier-1 sandbox — subprocess + RLIMIT_AS / RLIMIT_CPU + outer timeout.

The production default. Each :meth:`SubprocessSandbox.execute` call boots
a fresh ``python`` subprocess that:

1. Reads JSON args from stdin.
2. Re-validates the implementation against the allowed-imports set
   (defense-in-depth — the parent already validated, but a misconfigured
   parent shouldn't be the only line of defense).
3. Imports only the allowed modules.
4. Defines a function whose body is the implementation.
5. Calls it with ``**args``.
6. JSON-encodes the result to stdout; non-zero exit on failure.

The parent process wraps the call in :func:`asyncio.wait_for` for an
outer timeout, and (on POSIX) sets ``RLIMIT_AS`` + ``RLIMIT_CPU`` via a
preexec hook for memory + CPU caps. On Windows, resource limits are
not enforced (logged once at construction).

**What this does NOT protect against:**
* Network access — the subprocess can still hit the network. For network
  isolation, ship a third-party Docker / Firecracker / e2b backend.
* Filesystem reads — the subprocess inherits the parent's working dir
  and can read any file the parent can. Same recommendation.
* Sibling-subprocess spawning if the parent's CPU cap is high enough.
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from time import monotonic
from typing import Any

from loguru import logger

from orqest.sandbox._static import collect_issues, format_issues
from orqest.sandbox.protocol import ExecutionResult, ValidationError

_IS_POSIX = platform.system() != "Windows"
_WARNED_WINDOWS = False


def _warn_once_windows() -> None:
    global _WARNED_WINDOWS
    if not _IS_POSIX and not _WARNED_WINDOWS:
        logger.warning(
            "SubprocessSandbox: resource.setrlimit unavailable on Windows; "
            "RLIMIT_AS / RLIMIT_CPU caps will NOT be enforced. Outer "
            "asyncio.wait_for timeout still applies. Use a containerized "
            "backend for hard isolation."
        )
        _WARNED_WINDOWS = True


# --- Subprocess wrapper script ----------------------------------------------
# Runs as: ``python -c <_WRAPPER_SCRIPT>``. Stdin: JSON {"args":..., "code":...,
# "allowed_imports":[...]}. Stdout: JSON {"success":bool, "output":..., "error":..., "stdout": "..."}.

_WRAPPER_SCRIPT = '''
import ast
import io
import json
import sys
import traceback
from contextlib import redirect_stdout

_FORBIDDEN = {"eval","exec","compile","__import__","open","globals","locals",
              "vars","input","breakpoint"}
_FORBIDDEN_ATTRS = {"__class__","__bases__","__subclasses__","__mro__",
                    "__globals__","__builtins__","__import__","__loader__",
                    "__spec__","__code__","__closure__","__getattribute__",
                    "__reduce__","__reduce_ex__"}


def _root(name):
    return name.split(".", 1)[0]


def _validate(code, allowed):
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"syntax error: {exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root(alias.name) not in allowed:
                    return f"import {alias.name!r} not in allowed_imports"
        elif isinstance(node, ast.ImportFrom):
            if _root(node.module or "") not in allowed:
                return f"from {node.module!r} import not in allowed_imports"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN:
                return f"call to forbidden name {node.func.id!r}"
        elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
            return f"access to forbidden attribute {node.attr!r}"
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN:
            return f"reference to forbidden name {node.id!r}"
    return None


def _emit(payload):
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def _main():
    try:
        spec = json.loads(sys.stdin.read())
    except Exception as exc:
        _emit({"success": False, "error": f"failed to parse stdin spec: {exc}"})
        return

    code = spec.get("code", "")
    args = spec.get("args", {})
    allowed = set(spec.get("allowed_imports", []))

    issue = _validate(code, allowed)
    if issue:
        _emit({"success": False, "error": f"validation failed inside subprocess: {issue}"})
        return

    namespace = {"args": dict(args)}
    import importlib
    for module_name in allowed:
        try:
            namespace[_root(module_name)] = importlib.import_module(module_name)
        except ImportError as exc:
            _emit({"success": False, "error": f"allowed import {module_name!r} not available: {exc}"})
            return

    wrapped = (
        "def __orqest_tool(args):\\n"
        + "\\n".join("    " + line for line in code.splitlines())
        + "\\n__orqest_result = __orqest_tool(args)\\n"
    )

    stdout_buf = io.StringIO()
    try:
        with redirect_stdout(stdout_buf):
            exec(wrapped, namespace)
    except Exception as exc:
        _emit({
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "stdout": stdout_buf.getvalue(),
            "traceback": traceback.format_exc(),
        })
        return

    result = namespace.get("__orqest_result")
    try:
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        _emit({
            "success": False,
            "error": f"return value is not JSON-serializable: {exc}",
            "stdout": stdout_buf.getvalue(),
        })
        return

    _emit({"success": True, "output": result, "stdout": stdout_buf.getvalue()})


_main()
'''


def _make_preexec(memory_mb: int, timeout_s: float):
    """Return a preexec_fn that sets RLIMIT_AS + RLIMIT_CPU on POSIX.

    ``None`` on Windows (preexec_fn is unsupported there).
    """
    if not _IS_POSIX:
        return None

    import resource  # POSIX-only

    def _preexec() -> None:
        # Memory cap (address-space size, bytes)
        bytes_cap = int(memory_mb) * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (bytes_cap, bytes_cap))
        except (ValueError, OSError):
            pass
        # CPU-time cap (seconds, integer; round up; min 1s)
        cpu_cap = max(1, int(timeout_s) + 1)
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_cap, cpu_cap))
        except (ValueError, OSError):
            pass

    return _preexec


class SubprocessSandbox:
    """Tier-1 sandbox — subprocess with resource limits + outer timeout.

    See module docstring for what this DOES protect against (memory, CPU,
    timeout, in-process namespace bleed) and what it does NOT (network,
    filesystem reads, child subprocesses if CPU cap permits).
    """

    def __init__(self) -> None:
        _warn_once_windows()

    async def validate(
        self,
        code: str,
        *,
        allowed_imports: set[str],
    ) -> None:
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
        """Run code in a fresh subprocess. ``agent_id`` and ``dependencies``
        are accepted for Protocol conformance but ignored — Tier-1 has no
        per-agent venv concept (use Tier-2 :class:`DockerSandbox` for that).
        """
        # Re-validate at the parent (defense in depth)
        await self.validate(code, allowed_imports=allowed_imports)

        spec_json = json.dumps(
            {
                "code": code,
                "args": dict(args),
                "allowed_imports": sorted(allowed_imports),
            }
        )

        t0 = monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                _WRAPPER_SCRIPT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=_make_preexec(memory_mb, timeout_s),
            )
        except OSError as exc:
            # Infrastructure failure — couldn't even start subprocess.
            return ExecutionResult(
                success=False,
                error=f"failed to start subprocess: {exc}",
                duration_ms=(monotonic() - t0) * 1000.0,
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=spec_json.encode("utf-8")),
                timeout=timeout_s,
            )
        except TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:  # noqa: BLE001
                pass
            return ExecutionResult(
                success=False,
                error=f"sandbox execution timed out after {timeout_s:.2f}s",
                duration_ms=(monotonic() - t0) * 1000.0,
            )

        duration_ms = (monotonic() - t0) * 1000.0
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")

        if not stdout_text.strip():
            return ExecutionResult(
                success=False,
                error=(
                    f"subprocess produced no output (exit code {proc.returncode}); "
                    f"stderr: {stderr_text[:500]}"
                ),
                stdout=stderr_text,
                duration_ms=duration_ms,
            )

        try:
            payload = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            return ExecutionResult(
                success=False,
                error=(
                    f"subprocess output was not valid JSON ({exc}); "
                    f"raw stdout: {stdout_text[:500]}; stderr: {stderr_text[:200]}"
                ),
                stdout=stdout_text,
                duration_ms=duration_ms,
            )

        return ExecutionResult(
            success=bool(payload.get("success")),
            output=payload.get("output"),
            error=payload.get("error"),
            stdout=str(payload.get("stdout", "")),
            duration_ms=duration_ms,
        )

    async def __aenter__(self) -> SubprocessSandbox:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None


__all__ = ["SubprocessSandbox"]
