"""Generative UI primitives — agents that design their own surface.

The agent emits a typed :class:`UIComponentSpec`; the frontend resolves
a renderer by ``component_type`` and hot-loads it. Subsequent state
updates flow as :class:`UIDeltaEvent` records on the same SSE stream.

See :doc:`/concepts/generative_ui` for the full picture; this module hosts:

* :class:`UIComponentSpec[T]` + :class:`UIDeltaEvent` + :data:`UIDeltaOp`
  — the protocol primitives.
* :class:`ComponentRegistry` — per-Workbench schema registry.
* :class:`UIEmitter` — convenience facade for emitting init/delta/remove
  events on an :class:`EventBus`.
* First-party components organised in three layers:

  - **Compositional primitives:** :class:`PlanComponent`,
    :class:`ChartComponent`, :class:`TableComponent`,
    :class:`FormComponent`, :class:`TakeoverDialogComponent`,
    :class:`LayoutComponent`, :class:`TextComponent`,
    :class:`MarkdownComponent`, :class:`ImageComponent`,
    :class:`BadgeComponent`, :class:`ButtonComponent`,
    :class:`InputComponent`.
  - **Declarative grammars:** :class:`VegaChartComponent`,
    :class:`MermaidComponent`, :class:`LatexComponent`,
    :class:`JsonViewerComponent`.
  - **Sandboxed escape hatch:** :class:`SandboxedHTMLComponent`.
"""

from orqest.ui.components import (
    BadgeComponent,
    BadgeComponentData,
    BadgeTone,
    ButtonComponent,
    ButtonComponentData,
    ButtonVariant,
    ChartComponent,
    ChartComponentData,
    ChartKind,
    ChartSeries,
    ColumnKind,
    FieldKind,
    FormComponent,
    FormComponentData,
    FormField,
    ImageComponent,
    ImageComponentData,
    InputComponent,
    InputComponentData,
    InputKind,
    JsonViewerComponent,
    JsonViewerComponentData,
    LatexComponent,
    LatexComponentData,
    LayoutAlign,
    LayoutComponent,
    LayoutComponentData,
    LayoutDirection,
    MarkdownComponent,
    MarkdownComponentData,
    MermaidComponent,
    MermaidComponentData,
    PlanComponent,
    PlanComponentData,
    SandboxedHTMLComponent,
    SandboxedHTMLComponentData,
    TableColumn,
    TableComponent,
    TableComponentData,
    TakeoverDialogComponent,
    TakeoverDialogData,
    TakeoverKind,
    TextComponent,
    TextComponentData,
    TextTone,
    TextVariant,
    VegaChartComponent,
    VegaChartComponentData,
)
from orqest.ui.emitter import UIEmitter
from orqest.ui.events import (
    ui_delta_event_type,
    ui_init_event_type,
    ui_remove_event_type,
)
from orqest.ui.registry import ComponentRegistry, default_registry
from orqest.ui.spec import UIComponentSpec, UIDeltaEvent, UIDeltaOp

__all__ = [
    "BadgeComponent",
    "BadgeComponentData",
    "BadgeTone",
    "ButtonComponent",
    "ButtonComponentData",
    "ButtonVariant",
    "ChartComponent",
    "ChartComponentData",
    "ChartKind",
    "ChartSeries",
    "ColumnKind",
    "ComponentRegistry",
    "FieldKind",
    "FormComponent",
    "FormComponentData",
    "FormField",
    "ImageComponent",
    "ImageComponentData",
    "InputComponent",
    "InputComponentData",
    "InputKind",
    "JsonViewerComponent",
    "JsonViewerComponentData",
    "LatexComponent",
    "LatexComponentData",
    "LayoutAlign",
    "LayoutComponent",
    "LayoutComponentData",
    "LayoutDirection",
    "MarkdownComponent",
    "MarkdownComponentData",
    "MermaidComponent",
    "MermaidComponentData",
    "PlanComponent",
    "PlanComponentData",
    "SandboxedHTMLComponent",
    "SandboxedHTMLComponentData",
    "TableColumn",
    "TableComponent",
    "TableComponentData",
    "TakeoverDialogComponent",
    "TakeoverDialogData",
    "TakeoverKind",
    "TextComponent",
    "TextComponentData",
    "TextTone",
    "TextVariant",
    "UIComponentSpec",
    "UIDeltaEvent",
    "UIDeltaOp",
    "UIEmitter",
    "VegaChartComponent",
    "VegaChartComponentData",
    "default_registry",
    "ui_delta_event_type",
    "ui_init_event_type",
    "ui_remove_event_type",
]
