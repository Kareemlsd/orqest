"""Per-agent code executor — runs INSIDE the container.

For each ``execute_python(...)`` MCP call:

1. Static AST validation (reuses :mod:`orqest.sandbox._static` —
   default-deny imports, no eval/exec/dunder access).
2. Ensure the agent's per-agent ``.venv`` exists at
   ``/workspace/<session_id>/<agent_id>/venv/`` — created lazily with
   ``uv venv`` (~50ms).
3. For each declared dependency in ``dependencies`` not already in the
   venv: check against the ``allowed_packages`` allowlist (default-deny);
   if allowed, ``uv pip install <dep> --python <agent_venv>/bin/python``.
4. Spawn a subprocess into the agent's venv:
   ``<agent_venv>/bin/python -c <wrapper>`` with stdin = JSON args and
   stdout = JSON result. ``RLIMIT_AS`` + ``RLIMIT_CPU`` (POSIX) cap
   memory + CPU; outer ``asyncio.wait_for`` enforces wall-clock timeout.
5. JSON-decode the result into :class:`ExecutionResult`.

Per-package install gating is the load-bearing safety surface:
``allowed_packages`` is operator-controlled via the
``ORQEST_ALLOWED_PACKAGES`` env var; an LLM-declared dep that's not in
the set returns ``ExecutionResult(success=False, error="dependency 'X'
not in allowed_packages")`` and emits ``dependency.rejected``.
"""

from __future__ import annotations

import asyncio
import json
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from orqest.sandbox._static import collect_issues, format_issues
from orqest.sandbox.protocol import ExecutionResult

_IS_POSIX = platform.system() != "Windows"


@dataclass(frozen=True)
class ExecutorConfig:
    """Static configuration for the in-container executor."""

    workspace_root: Path = Path("/workspace")
    """Root for per-agent workspaces; ``<workspace_root>/<session_id>/<agent_id>/``."""

    session_id: str = ""
    """Per-session UUID — same as ``ORQEST_SESSION_ID`` env var."""

    allowed_packages: frozenset[str] = frozenset()
    """Operator-controlled allowlist for ``uv pip install`` targets.
    Default empty = block all installs (existing tools that need only
    stdlib still work)."""

    uv_path: str = "uv"
    """Path to the ``uv`` binary. Default uses ``$PATH``."""


_WRAPPER_SCRIPT = '''
import io
import json
import sys
import traceback
from contextlib import redirect_stdout

def _main():
    try:
        spec = json.loads(sys.stdin.read())
    except Exception as exc:
        sys.stdout.write(json.dumps({"success": False,
                                      "error": f"failed to parse stdin spec: {exc}"}))
        return

    code = spec.get("code", "")
    args = spec.get("args", {})
    namespace = {"args": dict(args)}

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
        sys.stdout.write(json.dumps({
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "stdout": stdout_buf.getvalue(),
            "traceback": traceback.format_exc(),
        }))
        return

    result = namespace.get("__orqest_result")
    try:
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        sys.stdout.write(json.dumps({
            "success": False,
            "error": f"return value is not JSON-serializable: {exc}",
            "stdout": stdout_buf.getvalue(),
        }))
        return

    sys.stdout.write(json.dumps({
        "success": True, "output": result, "stdout": stdout_buf.getvalue()
    }))

_main()
'''


def _make_preexec(memory_mb: int, timeout_s: float):
    """RLIMIT_AS + RLIMIT_CPU on POSIX; ``None`` on Windows."""
    if not _IS_POSIX:
        return None

    import resource

    def _preexec() -> None:
        bytes_cap = int(memory_mb) * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (bytes_cap, bytes_cap))
        except (ValueError, OSError):
            pass
        cpu_cap = max(1, int(timeout_s) + 1)
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_cap, cpu_cap))
        except (ValueError, OSError):
            pass

    return _preexec


class Executor:
    """In-container code executor.

    Holds per-session config; spawns per-agent venvs lazily; runs LLM
    code in subprocesses bound to those venvs.
    """

    def __init__(self, config: ExecutorConfig) -> None:
        self._config = config

    @property
    def config(self) -> ExecutorConfig:
        return self._config

    def agent_workspace(self, agent_id: str) -> Path:
        """``<workspace_root>/<session_id>/<agent_id>/``."""
        return self._config.workspace_root / self._config.session_id / agent_id

    def agent_venv_path(self, agent_id: str) -> Path:
        return self.agent_workspace(agent_id) / "venv"

    def agent_python(self, agent_id: str) -> Path:
        bin_dir = "Scripts" if not _IS_POSIX else "bin"
        return self.agent_venv_path(agent_id) / bin_dir / "python"

    async def ensure_venv(self, agent_id: str) -> None:
        """Create the agent's venv if it doesn't exist. ~50ms with uv."""
        venv_dir = self.agent_venv_path(agent_id)
        if (venv_dir / ("Scripts" if not _IS_POSIX else "bin")).exists():
            return  # Already exists
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            self._config.uv_path,
            "venv",
            str(venv_dir),
            "--python",
            sys.executable,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"uv venv failed for agent {agent_id!r}: "
                f"{stderr.decode('utf-8', errors='replace')}"
            )

    async def install_deps(
        self,
        agent_id: str,
        dependencies: list[str],
    ) -> tuple[bool, str | None]:
        """Install allowed deps into the agent's venv via ``uv pip``.

        Returns ``(ok, error)``. ``ok=False`` indicates either an
        allowlist-rejection (with the rejected pkg name in error) or
        an install failure.

        Default-deny: any dep whose package name (stripped of version
        specifier) is NOT in ``config.allowed_packages`` rejects.
        """
        if not dependencies:
            return True, None
        allowed = self._config.allowed_packages

        for dep in dependencies:
            pkg_name = _pkg_name(dep)
            if pkg_name not in allowed:
                return False, (
                    f"dependency {pkg_name!r} (from spec {dep!r}) not in "
                    f"allowed_packages={sorted(allowed) if allowed else 'empty'}"
                )

        proc = await asyncio.create_subprocess_exec(
            self._config.uv_path,
            "pip",
            "install",
            "--python",
            str(self.agent_python(agent_id)),
            "--quiet",
            *dependencies,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return False, (
                f"uv pip install failed: "
                f"{stderr.decode('utf-8', errors='replace')[:300]}"
            )
        return True, None

    async def execute(
        self,
        *,
        code: str,
        args: dict[str, Any],
        allowed_imports: set[str],
        agent_id: str,
        dependencies: list[str] | None = None,
        timeout_s: float = 5.0,
        memory_mb: int = 128,
    ) -> ExecutionResult:
        """Validate, ensure venv, install deps, run, return ExecutionResult."""
        # Static AST validation
        issues = collect_issues(code, allowed_imports=allowed_imports)
        if issues:
            return ExecutionResult(
                success=False,
                error=f"validation failed: {format_issues(issues)}",
                duration_ms=0.0,
            )

        t0 = monotonic()

        # Ensure venv + install deps
        try:
            await self.ensure_venv(agent_id)
        except Exception as exc:  # noqa: BLE001
            return ExecutionResult(
                success=False,
                error=f"venv setup failed: {exc}",
                duration_ms=(monotonic() - t0) * 1000.0,
            )

        if dependencies:
            ok, err = await self.install_deps(agent_id, dependencies)
            if not ok:
                return ExecutionResult(
                    success=False,
                    error=err or "dependency install failed",
                    duration_ms=(monotonic() - t0) * 1000.0,
                )

        # Run the implementation
        spec_json = json.dumps({"code": code, "args": dict(args)})
        try:
            proc = await asyncio.create_subprocess_exec(
                str(self.agent_python(agent_id)),
                "-c",
                _WRAPPER_SCRIPT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=_make_preexec(memory_mb, timeout_s),
                cwd=str(self.agent_workspace(agent_id)),
            )
        except OSError as exc:
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
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if not stdout_text.strip():
            return ExecutionResult(
                success=False,
                error=(
                    f"subprocess produced no output (exit {proc.returncode}); "
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
                    f"raw stdout: {stdout_text[:500]}"
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

    def cleanup_agent(self, agent_id: str) -> None:
        """Remove the agent's workspace dir + venv. Best-effort."""
        ws = self.agent_workspace(agent_id)
        if ws.exists():
            try:
                shutil.rmtree(ws)
            except OSError:
                pass


def _pkg_name(spec: str) -> str:
    """Strip version specifier and extras marker from a pip spec.

    Examples::

        _pkg_name("pandas") == "pandas"
        _pkg_name("pandas>=2.0") == "pandas"
        _pkg_name("pandas[extras]>=2.0") == "pandas"
        _pkg_name("git+https://...") → returns the full string (we don't
            install URLs by default; the allowlist won't match a URL anyway)

    Order matters: ``[`` (extras marker) is checked before version operators
    so that ``pandas[extras]>=2.0`` correctly normalizes to ``pandas`` for
    allowlist matching.
    """
    # Find the earliest delimiter — extras `[` must take precedence over
    # version operators (PEP 508 grammar puts extras BEFORE version)
    earliest = len(spec)
    for sep in ("[", "==", ">=", "<=", "!=", "~=", ">", "<", " ", "@"):
        idx = spec.find(sep)
        if 0 < idx < earliest:
            earliest = idx
    return spec[:earliest].strip()


__all__ = [
    "Executor",
    "ExecutorConfig",
]
