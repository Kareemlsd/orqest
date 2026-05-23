"""Tests for ``MarkdownComponent``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orqest.ui import MarkdownComponent, MarkdownComponentData


def test_markdown_component_round_trip() -> None:
    src = "# Heading\n\n- bullet\n- bullet\n\n```python\nprint(1)\n```"
    spec = MarkdownComponent(data=MarkdownComponentData(content=src))
    assert spec.component_type == "markdown"
    revived = MarkdownComponent.model_validate_json(spec.model_dump_json())
    assert revived.data.content == src


def test_markdown_content_required() -> None:
    with pytest.raises(ValidationError):
        MarkdownComponentData()  # type: ignore[call-arg]
