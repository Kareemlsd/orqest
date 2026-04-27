"""Auto-respawn middleware for the right-pane system tabs.

Subscribes to a session's :class:`~orqest.observability.EventBus` and on
the first (or any subsequent) event from a relevant family for that
session, ensures the matching system tab exists in the manifest. The
``ensure_system_tab`` helper is idempotent, so closing a tab and the
agent firing the same event family re-creates it cleanly.

This is what makes the **lazy-spawn, closeable** UX work: the user can
dismiss the Shell tab, the agent runs another command, and the tab
pops back. The user is never permanently rid of a system surface as
long as the corresponding tools are still being used.

Event-family → tab-kind mapping:

* ``tool.shell.* | tool.python.* | shell.stdout | shell.stderr | shell.exit``
  → ``shell``
* ``tool.fs.list_dir.*`` → ``files``
* ``tool.fs.write_file.* | tool.fs.edit_file.* | tool.fs.read_file.completed``
  → ``editor`` (with ``content_ref.path`` from the event payload, so
  multiple editor tabs coexist one-per-file)
* ``browser.*`` → ``browser`` (only when ``ENABLE_BROWSER`` is on; the
  tools wouldn't be registered otherwise)
* ``artifact.created`` with ``kind='report'`` → ``report``
* ``artifact.created`` with ``kind='chart'`` → ``chart_gallery``

The subscriber **never** reacts to ``tab.*`` events — that prevents a
loop where ensure_system_tab's own ``tab.opened`` re-triggers the handler.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from orqest.observability import AgentEvent, EventBus

from polymath.routers.tabs import ensure_system_tab

logger = logging.getLogger(__name__)


# Event-type prefix → (kind, default_title, payload-extractor) tuples.
# Order matters: shell prefixes are checked before fs because both could
# match a generic "tool." prefix; the more specific prefix wins.
_SHELL_PREFIXES: tuple[str, ...] = (
    "tool.shell.",
    "tool.python.",
    "shell.",  # shell.stdout / shell.stderr / shell.exit
)
_FILES_PREFIXES: tuple[str, ...] = ("tool.fs.list_dir",)
_EDITOR_PREFIXES: tuple[str, ...] = (
    "tool.fs.write_file",
    "tool.fs.edit_file",
    "tool.fs.read_file",
)
_BROWSER_PREFIXES: tuple[str, ...] = ("browser.",)
_MEMORY_PREFIXES: tuple[str, ...] = (
    "memory.stored",
    "memory.recalled",
    "memory.entry_updated",
    "memory.recall_empty",
    "memory.store_failed",
)
_AGENTS_PREFIXES: tuple[str, ...] = (
    "agent.spawned",
    "agent.registered",
    "agent.updated",
    "agent.completed",
    "agent.invocation_failed",
)


def _extract_path(event: AgentEvent) -> str | None:
    """Pull the touched file path out of a ``tool.fs.*`` event payload.

    Different tools name the field differently — ``write_file`` /
    ``edit_file`` / ``read_file`` use ``path``; some completion events
    nest the args under ``args``. This walks both shapes, defensively.
    """
    data = event.data or {}
    direct = data.get("path")
    if isinstance(direct, str) and direct:
        return direct
    args = data.get("args")
    if isinstance(args, dict):
        nested = args.get("path")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _editor_title(path: str) -> str:
    """Tab title for an editor surface — terminal segment of the path."""
    if "/" in path:
        return path.rsplit("/", 1)[-1] or path
    return path


def make_respawn_handler(session_id: str):
    """Build an async event handler bound to *session_id*.

    The handler is registered via :meth:`EventBus.subscribe_all` once per
    session. It dispatches to :func:`ensure_system_tab` based on the
    event type, with all DB / bus calls awaited inside the handler so
    every spawn is durable before the next event is processed.

    ``session_id`` may be either a UUID-shaped string or any opaque
    identifier (the workbench accepts arbitrary strings for testing
    fixtures). UUID parsing happens lazily so non-UUID ids still attach a
    valid handler — they just no-op since :func:`ensure_system_tab`
    requires a UUID.
    """
    try:
        sid: UUID | None = UUID(session_id)
    except (ValueError, TypeError):
        sid = None

    async def _handler(event: AgentEvent) -> None:
        if sid is None:
            return
        et = event.event_type or ""
        # Hard-skip our own emissions to prevent re-entry loops.
        if et.startswith("tab."):
            return
        try:
            if any(et.startswith(p) for p in _EDITOR_PREFIXES):
                # Editor — needs the path. Skip silently if absent (the
                # event is informational without a target file).
                path = _extract_path(event)
                if path:
                    await ensure_system_tab(
                        sid,
                        "editor",
                        title=_editor_title(path),
                        content_ref={"path": path},
                    )
                return
            if any(et.startswith(p) for p in _SHELL_PREFIXES):
                await ensure_system_tab(sid, "shell", title="Shell")
                return
            if any(et.startswith(p) for p in _FILES_PREFIXES):
                await ensure_system_tab(sid, "files", title="Files")
                return
            if any(et.startswith(p) for p in _BROWSER_PREFIXES):
                await ensure_system_tab(sid, "browser", title="Browser")
                return
            if et == "artifact.created":
                kind = (event.data or {}).get("kind")
                if kind == "report":
                    await ensure_system_tab(sid, "report", title="Report")
                elif kind == "chart":
                    await ensure_system_tab(
                        sid, "chart_gallery", title="Charts"
                    )
                return
            if any(et.startswith(p) for p in _MEMORY_PREFIXES):
                # The memory tab is the three-section semantic /
                # episodic / procedural browser. Spawning on first
                # store / recall makes the surface visible the moment
                # the agent's cognitive memory engages.
                await ensure_system_tab(sid, "memory", title="Memory")
                return
            if any(et.startswith(p) for p in _AGENTS_PREFIXES):
                # The agents tab shows the live sub-agent roster — name,
                # role, last confidence, capability_boundary flag.
                # Spawning on first registration / spawn makes the
                # multi-agent activity legible.
                await ensure_system_tab(sid, "agents", title="Agents")
                return
        except Exception as exc:  # noqa: BLE001 — never break the bus loop.
            logger.warning(
                "tab respawn handler failed for %s [%s]: %s", session_id, et, exc
            )

    # Give the handler a meaningful name so EventBus error logs identify it.
    _handler.__name__ = f"tab_respawn[{session_id}]"
    return _handler


def attach_respawn(bus: EventBus, session_id: str) -> Any:
    """Register the handler on *bus* and return the handler reference.

    The reference can be passed to :meth:`EventBus.unsubscribe_all` if a
    session ever needs to detach. In practice the bus dies with the
    runtime so explicit unsubscription is rarely needed.
    """
    handler = make_respawn_handler(session_id)
    bus.subscribe_all(handler)
    return handler
