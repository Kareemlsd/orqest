"""Per-Workbench :class:`ComponentRegistry`.

Backend-side schema registry mapping ``component_type`` →
:class:`UIComponentSpec` subclass. Used to:

* validate inbound JSON when an LLM produces a component spec as
  structured output;
* advertise available component types to the frontend resolver via a
  ``GET /ui/component-types`` endpoint.

Per-instance (not module-level singleton) so multi-tenant backends keep
component registrations isolated — matches the
:class:`Workbench`-as-service pattern that ``EventBus`` and ``Tracer``
already follow. No import-time side effects.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from orqest.ui.spec import UIComponentSpec


class ComponentRegistry:
    """Maps ``component_type`` → :class:`UIComponentSpec` subclass."""

    def __init__(self) -> None:
        self._specs: dict[str, type[UIComponentSpec[Any]]] = {}

    def register(
        self,
        spec_class: type[UIComponentSpec[Any]],
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a concrete :class:`UIComponentSpec` subclass.

        Reads the ``component_type`` Literal default off ``spec_class``;
        the discriminator must be set on the class (not the instance).
        Re-registering the same ``component_type`` is a no-op unless
        ``overwrite=True`` (the prior class is logged at WARN).
        """
        component_type = self._extract_type(spec_class)
        if component_type in self._specs and not overwrite:
            logger.warning(
                "Component {ct} already registered; pass overwrite=True to replace",
                ct=component_type,
            )
            return
        self._specs[component_type] = spec_class

    def get(self, component_type: str) -> type[UIComponentSpec[Any]] | None:
        """Return the registered spec class for ``component_type``, or ``None``."""
        return self._specs.get(component_type)

    def list_types(self) -> list[str]:
        """All registered component types, sorted."""
        return sorted(self._specs.keys())

    def validate_payload(
        self, component_type: str, payload: dict[str, Any]
    ) -> UIComponentSpec[Any] | None:
        """Hydrate a raw dict against the registered spec.

        Returns ``None`` on lookup miss or validation failure (logged
        at WARN). Best-effort — UI validation should never break agent
        execution.
        """
        cls = self._specs.get(component_type)
        if cls is None:
            return None
        try:
            return cls.model_validate(payload)
        except Exception as exc:
            logger.warning(
                "Component validation failed for {ct}: {e}", ct=component_type, e=exc,
            )
            return None

    def __contains__(self, component_type: str) -> bool:
        return component_type in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    @staticmethod
    def _extract_type(spec_class: type[UIComponentSpec[Any]]) -> str:
        """Read the Literal default off ``component_type`` field."""
        field = spec_class.model_fields.get("component_type")
        if field is None:
            raise ValueError(
                f"{spec_class.__name__} has no component_type field"
            )
        default = field.default
        if not isinstance(default, str):
            raise ValueError(
                f"{spec_class.__name__}.component_type must default to a "
                f"Literal[str]; got {default!r}"
            )
        return default


def default_registry() -> ComponentRegistry:
    """A :class:`ComponentRegistry` pre-loaded with first-party components.

    Three layers of generative-UI primitives ship in core:

    1. **Compositional** — :class:`PlanComponent`, :class:`ChartComponent`,
       :class:`TableComponent`, :class:`FormComponent`,
       :class:`TakeoverDialogComponent`, :class:`LayoutComponent`,
       :class:`TextComponent`, :class:`MarkdownComponent`,
       :class:`ImageComponent`, :class:`BadgeComponent`,
       :class:`ButtonComponent`, :class:`InputComponent`. The agent composes
       these to build arbitrary UI.
    2. **Declarative grammars** — :class:`VegaChartComponent`,
       :class:`MermaidComponent`, :class:`LatexComponent`,
       :class:`JsonViewerComponent`. Thin wrappers around external
       grammars; the agent emits the spec.
    3. **Sandboxed escape hatch** — :class:`SandboxedHTMLComponent`. The
       agent writes raw HTML/SVG; the frontend confines it in an iframe.
       The component registers in core unconditionally; consumers gate
       *rendering* / *emission* via their own config flag.
    """
    from orqest.ui.components import (
        BadgeComponent,
        ButtonComponent,
        ChartComponent,
        FormComponent,
        ImageComponent,
        InputComponent,
        JsonViewerComponent,
        LatexComponent,
        LayoutComponent,
        MarkdownComponent,
        MermaidComponent,
        PlanComponent,
        SandboxedHTMLComponent,
        TableComponent,
        TakeoverDialogComponent,
        TextComponent,
        VegaChartComponent,
    )

    reg = ComponentRegistry()
    # Existing first-party components.
    reg.register(PlanComponent)
    reg.register(ChartComponent)
    reg.register(TableComponent)
    reg.register(FormComponent)
    reg.register(TakeoverDialogComponent)
    # Layer 1 — compositional primitives.
    reg.register(LayoutComponent)
    reg.register(TextComponent)
    reg.register(MarkdownComponent)
    reg.register(ImageComponent)
    reg.register(BadgeComponent)
    reg.register(ButtonComponent)
    reg.register(InputComponent)
    # Layer 2 — declarative grammars.
    reg.register(VegaChartComponent)
    reg.register(MermaidComponent)
    reg.register(LatexComponent)
    reg.register(JsonViewerComponent)
    # Layer 3 — sandboxed escape hatch (frontend gates rendering).
    reg.register(SandboxedHTMLComponent)
    return reg
