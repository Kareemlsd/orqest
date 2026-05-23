"""Generative-UI tools — emit / update / remove typed UI components.

Three orchestrator-facing tools sit on top of the per-Workbench
:class:`~orqest.ui.ComponentRegistry` and the workbench's
:class:`~orqest.observability.EventBus`:

* :func:`emit_component` — publish a fresh component (``ui.<type>.init``).
  The agent picks the ``component_type`` and supplies a ``data`` payload
  shaped per the registered :class:`UIComponentSpec` subclass; this tool
  validates the payload, assigns / preserves a ``component_id``, and
  fires the typed event on the session's bus. Returns the assigned id
  so the agent can target it from the update / remove tools later.
* :func:`update_component` — patch a previously-emitted component via
  :class:`~orqest.ui.UIDeltaEvent` (replace / merge / append / remove
  semantics). The agent passes a dot-path into the component data + the
  new value; the frontend applies the op against the previously
  rendered component identified by ``component_id``.
* :func:`remove_component` — emit ``ui.<type>.remove`` so the frontend
  unmounts the component.

Validation failures, missing component types, and disabled-feature
gates surface as JSON ``{"error": ...}`` bodies — the agent reads the
error and responds in chat rather than throwing.

The :class:`~orqest.ui.components.SandboxedHTMLComponent` (Layer 3) is
gated on ``cfg.ENABLE_SANDBOXED_HTML``; the registry registers it
unconditionally so the backend can validate / round-trip the spec, but
emission is rejected when the flag is off.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from orqest.ui import UIDeltaOp, UIEmitter

from polymath.config import get_default_config
from polymath.db.models import Tab
from polymath.db.session import get_sessionmaker
from polymath.runtime import get_runtime
from polymath.state import PolymathState


_GATED_COMPONENT_TYPES = {"sandboxed_html"}


def _emitter_for(session_id: str) -> UIEmitter:
    """Build a :class:`UIEmitter` bound to the session's event bus."""
    bus = get_runtime(session_id).workbench.event_bus
    return UIEmitter(bus, agent_name=f"polymath[{session_id}]")


def _gate_check(component_type: str) -> str | None:
    """Return an error string if ``component_type`` is gated off, else None."""
    if component_type not in _GATED_COMPONENT_TYPES:
        return None
    cfg = get_default_config()
    if component_type == "sandboxed_html" and not cfg.ENABLE_SANDBOXED_HTML:
        return (
            "sandboxed_html disabled; set POLYMATH_ENABLE_SANDBOXED_HTML=1 "
            "to enable Layer 3 escape hatch."
        )
    return None


async def _ensure_component_tab(
    session_id: str,
    *,
    component_id: str,
    component_type: str,
    target_tab_id_raw: Any,
) -> str | None:
    """Bind ``component_id`` to a ``kind='component'`` right-pane tab.

    ``target_tab_id_raw`` is the value at ``metadata.target_tab_id`` from
    the agent's :func:`emit_component` call, if any. When set and valid,
    we append the component to the existing tab's binding list. When
    absent (or invalid), we auto-create a new tab so every emitted
    component lands somewhere visible.

    Returns the tab id the component is bound to, or ``None`` on
    failures (which we swallow rather than fail the emit — the typed
    ``ui.<type>.init`` event still fires and the frontend's wildcard
    ``CanvasTab`` continues to render the component during migration).
    """
    # Late import — this module is loaded at agent construction time and
    # we want the routers/tabs imports to stay lazy to avoid the cycle
    # that bites :mod:`polymath.tab_respawn`.
    from polymath.routers.tabs import _emit, _serialize, _utc_now_naive

    try:
        sid = UUID(session_id)
    except (ValueError, TypeError):
        return None

    target_tab_id: UUID | None = None
    if isinstance(target_tab_id_raw, str) and target_tab_id_raw:
        try:
            target_tab_id = UUID(target_tab_id_raw)
        except ValueError:
            target_tab_id = None

    sm = get_sessionmaker()
    now = _utc_now_naive()
    try:
        async with sm() as db:
            if target_tab_id is not None:
                tab = await db.get(Tab, target_tab_id)
                if (
                    tab is not None
                    and tab.session_id == sid
                    and tab.kind == "component"
                    and tab.status == "open"
                ):
                    bindings = list(
                        (tab.content_ref or {}).get("component_ids") or []
                    )
                    if component_id not in bindings:
                        bindings.append(component_id)
                    tab.content_ref = {**(tab.content_ref or {}), "component_ids": bindings}
                    tab.last_activity_at = now
                    tab.updated_at = now
                    db.add(tab)
                    await db.commit()
                    await db.refresh(tab)
                    await _emit(sid, "tab.updated", _serialize(tab))
                    return str(tab.id)
                # Fall-through: target id supplied but invalid → spawn fresh.

            # Spawn a fresh component-kind tab carrying the new component.
            from sqlmodel import select

            existing_positions = [
                p
                for p in (
                    await db.execute(
                        select(Tab.position).where(
                            Tab.session_id == sid, Tab.status == "open"
                        )
                    )
                )
                .scalars()
                .all()
                if p is not None
            ]
            position = (max(existing_positions) + 1) if existing_positions else 0
            new_tab = Tab(
                id=uuid4(),
                session_id=sid,
                kind="component",
                title=_default_component_title(component_type),
                position=position,
                pinned=False,
                status="open",
                content_ref={"component_ids": [component_id]},
                metadata_json={"primary_component_type": component_type},
                created_at=now,
                updated_at=now,
                last_activity_at=now,
            )
            db.add(new_tab)
            await db.commit()
            await db.refresh(new_tab)
        await _emit(sid, "tab.opened", _serialize(new_tab))
        return str(new_tab.id)
    except Exception:  # noqa: BLE001 — best-effort binding; never fail emit.
        return None


def _default_component_title(component_type: str) -> str:
    """Sensible default tab title when the agent doesn't supply one."""
    pretty = {
        "vega_chart": "Chart",
        "mermaid": "Diagram",
        "latex": "Math",
        "json_viewer": "JSON",
        "markdown": "Notes",
        "table": "Table",
        "image": "Image",
        "sandboxed_html": "Sandbox",
        "form": "Form",
        "layout": "Layout",
        "text": "Text",
        "badge": "Badge",
        "button": "Button",
        "input": "Input",
    }
    return pretty.get(component_type, component_type.replace("_", " ").title())


# ---- emit_component ---------------------------------------------------


async def _emit_component(
    ctx: RunContext[PolymathState],
    component_type: Annotated[
        str,
        "Discriminator for the registered UIComponentSpec subclass — e.g. "
        "'layout', 'text', 'markdown', 'image', 'badge', 'button', "
        "'input', 'vega_chart', 'mermaid', 'latex', 'json_viewer', "
        "'chart', 'table', 'plan', 'takeover_dialog', 'sandboxed_html'.",
    ],
    data: Annotated[
        dict,
        "Component data; shape depends on component_type. See the matching "
        "UIComponentSpec subclass for fields.",
    ],
    component_id: Annotated[
        str | None,
        "Optional stable id. When omitted, one is generated and returned "
        "so subsequent update/remove calls can target the component.",
    ] = None,
    metadata: Annotated[
        dict | None,
        "Optional metadata blob attached to the component envelope.",
    ] = None,
) -> str:
    """Emit a typed UI component for the frontend to render.

    Validates ``data`` against the registered component class and emits
    a ``ui.<component_type>.init`` event. Returns the assigned
    ``component_id`` so the agent can later update or remove it.
    """
    sid = ctx.deps.session_id
    workbench = get_runtime(sid).workbench
    spec_cls = workbench.ui_registry.get(component_type)
    if spec_cls is None:
        return json.dumps(
            {
                "error": (
                    f"unknown component_type: {component_type!r}. "
                    f"Registered types: {workbench.ui_registry.list_types()}"
                )
            }
        )
    gate_error = _gate_check(component_type)
    if gate_error is not None:
        return json.dumps({"error": gate_error})
    component_id = component_id or f"{component_type}-{uuid4().hex[:8]}"
    try:
        spec = spec_cls.model_validate(
            {
                "component_type": component_type,
                "component_id": component_id,
                "data": data,
                "metadata": metadata or {},
            }
        )
    except Exception as exc:  # noqa: BLE001 — surface as JSON
        return json.dumps({"error": f"validation failed: {exc}"})

    # Bind the new component to a right-pane tab. If the agent passed
    # ``metadata.target_tab_id``, append this component to that tab's
    # binding list (so multiple components can group inside one tab).
    # Otherwise auto-create a fresh ``kind='component'`` tab carrying the
    # new component as its sole binding. Either way the frontend's
    # ``TabComponentRenderer`` reads the tab's ``content_ref.component_ids``
    # to decide what to render.
    target_tab_id_raw = (metadata or {}).get("target_tab_id")
    bound_tab_id = await _ensure_component_tab(
        sid,
        component_id=component_id,
        component_type=component_type,
        target_tab_id_raw=target_tab_id_raw,
    )
    await _emitter_for(sid).init(spec)
    return json.dumps(
        {
            "component_id": component_id,
            "component_type": component_type,
            "tab_id": bound_tab_id,
        }
    )


# ---- update_component -------------------------------------------------


_VALID_OPS: tuple[UIDeltaOp, ...] = ("replace", "merge", "append", "remove")


async def _update_component(
    ctx: RunContext[PolymathState],
    component_id: Annotated[str, "ID returned by emit_component."],
    component_type: Annotated[
        str,
        "Discriminator for the component being updated. Must match the "
        "component_type used when the component was emitted.",
    ],
    op: Annotated[
        str,
        "Patch operation: 'replace' | 'merge' | 'append' | 'remove'. "
        "Append targets list-valued paths (e.g. layout.children, table "
        "rows). Merge does a shallow dict merge.",
    ],
    path: Annotated[
        str,
        "Dot-path into the component data, e.g. 'children.0.label'. "
        "Empty string targets the data root.",
    ] = "",
    value: Annotated[
        Any,
        "Replacement / merge / append payload. Ignored for op='remove'.",
    ] = None,
) -> str:
    """Patch a previously-emitted component.

    Emits ``ui.<component_type>.delta`` carrying a
    :class:`~orqest.ui.UIDeltaEvent`. The frontend applies the op
    against the previously rendered component identified by
    ``component_id``; an unknown id is treated as a no-op (the consumer
    can re-fetch via the snapshot endpoint).
    """
    sid = ctx.deps.session_id
    if op not in _VALID_OPS:
        return json.dumps(
            {"error": f"invalid op {op!r}; expected one of {list(_VALID_OPS)}"}
        )
    workbench = get_runtime(sid).workbench
    if workbench.ui_registry.get(component_type) is None:
        return json.dumps(
            {
                "error": (
                    f"unknown component_type: {component_type!r}. "
                    f"Registered types: {workbench.ui_registry.list_types()}"
                )
            }
        )
    await _emitter_for(sid).delta(
        component_id=component_id,
        component_type=component_type,
        op=op,  # type: ignore[arg-type]
        path=path,
        value=value,
    )
    return json.dumps(
        {
            "ok": True,
            "component_id": component_id,
            "component_type": component_type,
            "op": op,
            "path": path,
        }
    )


# ---- remove_component -------------------------------------------------


async def _remove_component(
    ctx: RunContext[PolymathState],
    component_id: Annotated[str, "ID returned by emit_component."],
    component_type: Annotated[
        str,
        "Discriminator for the component being removed. Must match the "
        "component_type used when the component was emitted.",
    ],
) -> str:
    """Remove a previously-emitted component.

    Emits ``ui.<component_type>.remove`` so the frontend unmounts the
    component.
    """
    sid = ctx.deps.session_id
    workbench = get_runtime(sid).workbench
    if workbench.ui_registry.get(component_type) is None:
        return json.dumps(
            {
                "error": (
                    f"unknown component_type: {component_type!r}. "
                    f"Registered types: {workbench.ui_registry.list_types()}"
                )
            }
        )
    await _emitter_for(sid).remove(
        component_id=component_id, component_type=component_type
    )
    return json.dumps(
        {
            "ok": True,
            "component_id": component_id,
            "component_type": component_type,
        }
    )


emit_component = Tool(_emit_component, name="emit_component")
update_component = Tool(_update_component, name="update_component")
remove_component = Tool(_remove_component, name="remove_component")
