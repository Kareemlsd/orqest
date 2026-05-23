"""PermissionGate — controls auto-discovery of MCP tools.

A remote MCP server is a code-execution surface. Auto-registering a
tool from an arbitrary server without consent is a security risk; the
gate is the explicit "yes" boundary.

Default policy is :class:`DenyAll` — discovery is opt-in. Consumers
who want auto-discovery wire :class:`AllowAll` (development) or
:class:`AllowList` (production with regex allowlist).
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable


@runtime_checkable
class PermissionGate(Protocol):
    """Decide whether a tool name may be discovered + registered at runtime."""

    async def allow(self, tool_name: str) -> bool: ...


class AllowAll:
    """Permit any tool name. Use only for development / trusted environments."""

    async def allow(self, tool_name: str) -> bool:
        return True


class DenyAll:
    """Deny every discovery. The default — discovery is opt-in."""

    async def allow(self, tool_name: str) -> bool:
        return False


class AllowList:
    """Permit tool names matching any of the supplied regex patterns.

    Patterns are compiled with :func:`re.search` semantics — they match
    anywhere in the tool name. Anchor with ``^…$`` for full-name matches.
    """

    def __init__(self, patterns: list[str]) -> None:
        self._patterns = [re.compile(p) for p in patterns]

    async def allow(self, tool_name: str) -> bool:
        return any(p.search(tool_name) for p in self._patterns)
