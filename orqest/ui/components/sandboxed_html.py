"""``SandboxedHTMLComponent`` — iframe-confined raw HTML / SVG / restricted JS.

The escape hatch for cases where neither compositional primitives
(Layer 1) nor declarative grammars (Layer 2) are enough. The frontend
renders the HTML inside an ``<iframe sandbox="allow-scripts">`` with a
strict CSP — no parent-document access, no network unless explicitly
allowed via ``csp_extra``. Polymath additionally gates the registration
of this component behind ``ENABLE_SANDBOXED_HTML`` so production
deployments stay locked-down by default.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from orqest.ui.spec import UIComponentSpec


class SandboxedHTMLComponentData(BaseModel):
    html: str
    """Raw HTML / SVG / restricted JS. Rendered in an iframe with
    sandbox="allow-scripts" and a strict CSP. No parent-document
    access, no network unless allowed via the iframe csp."""
    height_px: int = 400
    """Fixed height in CSS pixels — iframes don't auto-size."""
    csp_extra: str = ""
    """Additional CSP directives merged onto the default. Empty by default."""


class SandboxedHTMLComponent(UIComponentSpec[SandboxedHTMLComponentData]):
    component_type: Literal["sandboxed_html"] = "sandboxed_html"
    data: SandboxedHTMLComponentData
