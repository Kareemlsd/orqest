"""Tests for ``SandboxedHTMLComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import SandboxedHTMLComponent, SandboxedHTMLComponentData


def test_sandboxed_html_default_height() -> None:
    spec = SandboxedHTMLComponent(
        data=SandboxedHTMLComponentData(html="<p>hi</p>")
    )
    assert spec.component_type == "sandboxed_html"
    assert spec.data.height_px == 400
    assert spec.data.csp_extra == ""


def test_sandboxed_html_round_trip() -> None:
    spec = SandboxedHTMLComponent(
        data=SandboxedHTMLComponentData(
            html="<svg><circle r='10'/></svg>",
            height_px=200,
            csp_extra="img-src 'self' https://example.com;",
        )
    )
    revived = SandboxedHTMLComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.html == "<svg><circle r='10'/></svg>"
    assert revived.data.height_px == 200
    assert "img-src" in revived.data.csp_extra


def test_sandboxed_html_html_required() -> None:
    with pytest.raises(ValidationError):
        SandboxedHTMLComponentData()  # type: ignore[call-arg]
