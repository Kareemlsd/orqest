"""Typed payloads used by the sandbox manager and tools."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ExecResult(BaseModel):
    """Outcome of running a command in a sandbox."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    duration_ms: int = 0


class FileEntry(BaseModel):
    """One row in a sandbox directory listing."""

    name: str
    path: str
    kind: Literal["file", "dir"]
    size: int = 0
    modified_at: datetime | None = None


class ListDirResult(BaseModel):
    """A scoped directory listing."""

    path: str
    entries: list[FileEntry] = Field(default_factory=list)
    truncated: bool = False


class ReadFileResult(BaseModel):
    """Read-file payload with the path echoed back."""

    path: str
    text: str
    truncated: bool = False
    size: int = 0


class WriteFileResult(BaseModel):
    path: str
    bytes_written: int


class EditFileResult(BaseModel):
    path: str
    replacements: int
    bytes_written: int
