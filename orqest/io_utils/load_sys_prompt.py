"""Utility to load system prompts from a designated folder."""
from __future__ import annotations

import inspect
from pathlib import Path


def _find_upwards(start: Path, target_dirname: str) -> Path | None:
    for parent in [start] + list(start.parents):
        candidate = parent / target_dirname
        if candidate.is_dir():
            return candidate
    return None


def load_sys_prompt(filename: str, start: str | Path | None = None) -> str:
    """
    Load a system prompt by searching upwards for a 'system_prompts' folder,
    starting from the caller's file location (preferred) or from `start`/cwd.

    Args:
        filename: Name of the .txt file inside system_prompts.
        start: Optional explicit starting path (file or directory). If not provided,
               we try the caller's file directory; if unavailable, we use cwd.

    Returns:
        The content of the system prompt file.

    Raises:
        RuntimeError: If the folder or file cannot be found/read.
    """
    # Resolve start path
    if start is not None:
        start_path = Path(start).resolve()
        if start_path.is_file():
            start_path = start_path.parent
    else:
        # Try caller's file; fall back to cwd for REPL/notebooks
        frame = inspect.stack()[1]  # immediate caller
        caller_file = frame.filename
        if caller_file and caller_file not in ("<stdin>", "<string>"):
            start_path = Path(caller_file).resolve().parent
        else:
            start_path = Path.cwd().resolve()

    system_prompts_dir = _find_upwards(start_path, "system_prompts")
    if system_prompts_dir is None:
        raise RuntimeError(
            f"Could not find a 'system_prompts' folder starting from {start_path}"
        )

    file_path = system_prompts_dir / filename
    if not file_path.is_file():
        raise RuntimeError(f"System prompt file not found: {file_path}")

    try:
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to load system prompt from {file_path}: {e}")
