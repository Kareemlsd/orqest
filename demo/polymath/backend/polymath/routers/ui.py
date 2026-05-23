"""Generative-UI manifest endpoints — frontend listener / resolver discovery.

The frontend's ``useSidecar`` hook needs to know which SSE event types to
subscribe to, and the component resolver needs to know which
``component_type`` discriminators are valid. Hard-coding either list in
the frontend is a maintenance bottleneck — every time Orqest gains a new
first-party UI component, the frontend's whitelist drifts.

These endpoints expose the backend's source of truth so the frontend can
self-configure on session boot:

* ``GET /sessions/{sid}/ui/event-types`` — every SSE event type the UI
  should listen for: a static base (legacy plan / tool / agent /
  takeover events) plus a dynamic suffix per registered component
  (``ui.<type>.{init,delta,remove}``).
* ``GET /sessions/{sid}/ui/component-types`` — the bare list of
  registered ``component_type`` values; the frontend uses this to
  validate inbound spec payloads against known types before resolving a
  renderer.

Mirrors the pattern used by :mod:`polymath.routers.events` and
:mod:`polymath.routers.snapshot` — ``APIRouter(prefix="/sessions")``,
async endpoints, no FastAPI dependencies. Per-session because each
runtime owns its own ``Workbench.ui_registry``; in practice the
first-party catalog is identical across sessions today, but exposing
it per-session keeps the door open for session-scoped custom
components without a breaking API change.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from orqest.ui import (
    ui_delta_event_type,
    ui_init_event_type,
    ui_remove_event_type,
)

from polymath.runtime import get_runtime

router = APIRouter(prefix="/sessions", tags=["ui"])


# Static base whitelist — the legacy event types Polymath emits today.
# Mirrors the frontend's existing ``EVENT_TYPES`` array in
# ``useSidecar.ts``. Kept in sync until the frontend migrates to
# fetching this list at session boot.
_STATIC_EVENT_TYPES: tuple[str, ...] = (
    "heartbeat",
    "plan.init",
    "plan.task.updated",
    "tool.before",
    "tool.after",
    "tool.error",
    "memory.stored",
    "memory.recalled",
    "metacognition.confidence",
    "agent.spawned",
    "agent.completed",
    "agent.registered",
    "agent.updated",
    "agent.invocation_failed",
    "takeover.activated",
    "takeover.released",
    "shell.stdout",
    "shell.exit",
    "browser.action",
    "artifact.created",
    "tool.web_search.started",
    "tool.web_search.completed",
    "tool.web_fetch.started",
    "tool.web_fetch.completed",
    # Right-pane tab manifest events (see :mod:`polymath.routers.tabs`).
    "tab.opened",
    "tab.updated",
    "tab.closed",
    "tab.focused",
    "tab.restored",
    # Cognitive-backbone surfacing — visible counterparts of the
    # invisible features (see :mod:`polymath.tab_respawn` for which of
    # these spawn system tabs).
    "healing.detection",
    "healing.action",
    "healing.model_fallback",
    "healing.retry_initiated",
    "healing.model_chain_exhausted",
    "metacognition.redecomposition_triggered",
    "memory.entry_updated",
    "memory.recall_empty",
    "memory.store_failed",
    # Per-turn chat metadata — feeds the chrome's metadata strip
    # (`12.3s · 4 tools · 1.2k tokens`) and the session-header Context
    # token-usage ring.
    "chat.turn.completed",
)


@router.get("/{sid}/ui/event-types")
async def list_event_types(sid: UUID) -> dict[str, list[str]]:
    """Return the SSE event-type whitelist the frontend should subscribe to.

    Combines the static base (legacy plan / tool / agent / takeover
    events) with the dynamic ``ui.<type>.{init,delta,remove}`` triplet
    for every component registered on the session's
    :class:`~orqest.ui.ComponentRegistry`.
    """
    runtime = get_runtime(str(sid))
    registry = runtime.workbench.ui_registry
    types: list[str] = list(_STATIC_EVENT_TYPES)
    for component_type in registry.list_types():
        types.append(ui_init_event_type(component_type))
        types.append(ui_delta_event_type(component_type))
        types.append(ui_remove_event_type(component_type))
    return {"event_types": types}


@router.get("/{sid}/ui/component-types")
async def list_component_types(sid: UUID) -> dict[str, list[str]]:
    """Return the registered :class:`UIComponentSpec` discriminators.

    The frontend uses this to validate inbound ``ui.<type>.init``
    payloads against the set of known component types before resolving
    a renderer.
    """
    runtime = get_runtime(str(sid))
    return {"component_types": runtime.workbench.ui_registry.list_types()}
