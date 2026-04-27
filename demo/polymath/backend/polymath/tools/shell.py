"""Shell + Python execution tools scoped to the session sandbox."""

from __future__ import annotations

import json
from typing import Annotated

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from polymath.runtime import emit
from polymath.sandbox.manager import SandboxError, get_manager
from polymath.state import PolymathState


async def _run_command(
    ctx: RunContext[PolymathState],
    command: Annotated[
        str,
        "Shell command (bash -c '<command>'). E.g. 'pip install pandas' "
        "or 'python benchmark.py'. Stdout + stderr are captured; output "
        "is streamed as events for the Shell tab.",
    ],
    timeout_s: Annotated[int, "Max seconds before the command is killed."] = 120,
) -> str:
    """Run a shell command inside /workspace. Returns stdout/stderr + exit code."""
    sid = ctx.deps.session_id
    await emit(sid, "tool.shell.run_command.started", {"command": command})
    try:
        code, stdout, stderr, truncated = await get_manager().exec(
            sid, ["bash", "-lc", command], timeout_s=timeout_s
        )
    except SandboxError as exc:
        await emit(
            sid, "tool.shell.run_command.error", {"command": command, "error": str(exc)}
        )
        return json.dumps({"error": str(exc), "exit_code": -1})

    # Emit a stdout event (truncated) so the Shell tab can render a live feed.
    if stdout:
        await emit(
            sid,
            "shell.stdout",
            {"command": command, "text": stdout[:4000], "truncated": truncated},
        )
    if stderr:
        await emit(sid, "shell.stderr", {"command": command, "text": stderr[:4000]})
    await emit(
        sid,
        "tool.shell.run_command.completed",
        {
            "command": command,
            "exit_code": code,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
        },
    )
    return json.dumps(
        {
            "exit_code": code,
            "stdout": stdout[:8000],
            "stderr": stderr[:4000],
            "truncated": truncated,
        }
    )


async def _run_python_snippet(
    ctx: RunContext[PolymathState],
    code: Annotated[
        str,
        "A Python snippet to execute in the sandbox. Scripts writing files "
        "to /workspace are persisted across calls.",
    ],
    timeout_s: Annotated[int, "Max seconds before the interpreter is killed."] = 60,
) -> str:
    """Shortcut for ``python3 -c '<code>'``. Returns stdout/stderr + exit code."""
    sid = ctx.deps.session_id
    await emit(
        sid,
        "tool.python.run_snippet.started",
        {"bytes": len(code)},
    )
    try:
        exit_code, stdout, stderr, truncated = await get_manager().exec(
            sid, ["python3", "-c", code], timeout_s=timeout_s
        )
    except SandboxError as exc:
        await emit(sid, "tool.python.run_snippet.error", {"error": str(exc)})
        return json.dumps({"error": str(exc), "exit_code": -1})
    if stdout:
        await emit(
            sid,
            "shell.stdout",
            {"command": "python3 -c", "text": stdout[:4000], "truncated": truncated},
        )
    if stderr:
        await emit(
            sid,
            "shell.stderr",
            {"command": "python3 -c", "text": stderr[:4000]},
        )
    await emit(
        sid,
        "tool.python.run_snippet.completed",
        {
            "exit_code": exit_code,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
        },
    )
    return json.dumps(
        {
            "exit_code": exit_code,
            "stdout": stdout[:8000],
            "stderr": stderr[:4000],
            "truncated": truncated,
        }
    )


run_command = Tool(_run_command, name="run_command")
run_python_snippet = Tool(_run_python_snippet, name="run_python_snippet")
