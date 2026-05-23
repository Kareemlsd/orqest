"""SSE event-type conventions for generative UI.

Three event-type families per component:

* ``ui.<component_type>.init``   — full :class:`UIComponentSpec`
* ``ui.<component_type>.delta``  — partial :class:`UIDeltaEvent`
* ``ui.<component_type>.remove`` — payload ``{component_id}``

Centralising the format here keeps the Polymath frontend (and any
other consumer) decoupled from the string conventions — they call
:func:`ui_init_event_type` etc. and stay forward-compatible.
"""

from __future__ import annotations


def ui_init_event_type(component_type: str) -> str:
    return f"ui.{component_type}.init"


def ui_delta_event_type(component_type: str) -> str:
    return f"ui.{component_type}.delta"


def ui_remove_event_type(component_type: str) -> str:
    return f"ui.{component_type}.remove"
