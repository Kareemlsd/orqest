"""Filesystem tools — scoped to the session's sandbox ``/workspace``.

Every tool reads and writes inside one container. Callers (the agent) see
paths relative to ``/workspace`` — ``notes/todo.md`` → ``/workspace/notes/todo.md``
inside the sandbox. :class:`~polymath.sandbox.manager.SandboxError` is raised
for absolute paths or ``..`` traversal attempts.
"""

from __future__ import annotations

import json
from typing import Annotated

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from polymath.runtime import emit
from polymath.sandbox.manager import SandboxError, get_manager
from polymath.state import PolymathState

_MAX_READ_BYTES = 200_000


async def _read_file(
    ctx: RunContext[PolymathState],
    path: Annotated[str, "Path relative to /workspace (e.g. 'notes/todo.md')."],
) -> str:
    """Read a text file from the sandbox. Binary files return a truncated
    marker — use ``shell.run_command('file …')`` to inspect."""
    sid = ctx.deps.session_id
    await emit(sid, "tool.fs.read_file.started", {"path": path})
    try:
        data, truncated = await get_manager().get_file(sid, path, max_bytes=_MAX_READ_BYTES)
    except SandboxError as exc:
        await emit(sid, "tool.fs.read_file.error", {"path": path, "error": str(exc)})
        return json.dumps({"error": str(exc)})
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        await emit(sid, "tool.fs.read_file.completed", {"path": path, "binary": True})
        return json.dumps({"path": path, "binary": True, "bytes": len(data)})
    await emit(
        sid,
        "tool.fs.read_file.completed",
        {"path": path, "bytes": len(data), "truncated": truncated},
    )
    return json.dumps({"path": path, "text": text, "truncated": truncated})


async def _write_file(
    ctx: RunContext[PolymathState],
    path: Annotated[str, "Path relative to /workspace."],
    content: Annotated[str, "UTF-8 text to write (overwrites). Parent dirs auto-created."],
) -> str:
    """Create or overwrite a text file. Emits ``tool.fs.write_file.*`` events."""
    sid = ctx.deps.session_id
    await emit(sid, "tool.fs.write_file.started", {"path": path, "bytes": len(content)})
    try:
        # Ensure parent dir exists before put_archive tries to place the file.
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent:
            code, _, err, _ = await get_manager().exec(
                sid, ["mkdir", "-p", f"/workspace/{parent}"]
            )
            if code != 0:
                raise SandboxError(err.strip() or f"mkdir {parent} failed")
        written = await get_manager().put_file(sid, path, content.encode("utf-8"))
    except SandboxError as exc:
        await emit(sid, "tool.fs.write_file.error", {"path": path, "error": str(exc)})
        return json.dumps({"error": str(exc)})
    await emit(sid, "tool.fs.write_file.completed", {"path": path, "bytes": written})
    return json.dumps({"path": path, "bytes_written": written})


async def _edit_file(
    ctx: RunContext[PolymathState],
    path: Annotated[str, "Path relative to /workspace."],
    old: Annotated[str, "Substring to find. Must be unique within the file."],
    new: Annotated[str, "Replacement text."],
) -> str:
    """Single-shot find-and-replace. Fails if *old* isn't unique."""
    sid = ctx.deps.session_id
    await emit(sid, "tool.fs.edit_file.started", {"path": path})
    try:
        data, _ = await get_manager().get_file(sid, path, max_bytes=_MAX_READ_BYTES)
        text = data.decode("utf-8")
        count = text.count(old)
        if count == 0:
            raise SandboxError(f"old-string not found in {path}")
        if count > 1:
            raise SandboxError(
                f"old-string appears {count} times in {path}; make it unique"
            )
        updated = text.replace(old, new, 1)
        written = await get_manager().put_file(sid, path, updated.encode("utf-8"))
    except SandboxError as exc:
        await emit(sid, "tool.fs.edit_file.error", {"path": path, "error": str(exc)})
        return json.dumps({"error": str(exc)})
    await emit(
        sid,
        "tool.fs.edit_file.completed",
        {"path": path, "replacements": 1, "bytes": written},
    )
    return json.dumps({"path": path, "replacements": 1, "bytes_written": written})


async def _list_dir(
    ctx: RunContext[PolymathState],
    path: Annotated[str, "Directory relative to /workspace. Use '' for root."] = "",
    limit: Annotated[int, "Max entries to return."] = 200,
) -> str:
    """List a directory inside the sandbox.

    On error (missing path, not-a-directory, or sandbox failure) returns
    ``{"path": ..., "entries": [], "error": "..."}`` so the agent can
    keep its iteration scaffold while still seeing the diagnosis.
    """
    sid = ctx.deps.session_id
    await emit(sid, "tool.fs.list_dir.started", {"path": path})
    try:
        rows, truncated = await get_manager().list_dir(sid, path, limit=limit)
    except SandboxError as exc:
        await emit(sid, "tool.fs.list_dir.error", {"path": path, "error": str(exc)})
        return json.dumps({"path": path, "entries": [], "error": str(exc)})
    await emit(
        sid,
        "tool.fs.list_dir.completed",
        {"path": path, "count": len(rows), "truncated": truncated},
    )
    return json.dumps({"path": path, "entries": rows, "truncated": truncated})


read_file = Tool(_read_file, name="read_file")
write_file = Tool(_write_file, name="write_file")
edit_file = Tool(_edit_file, name="edit_file")
list_dir = Tool(_list_dir, name="list_dir")
