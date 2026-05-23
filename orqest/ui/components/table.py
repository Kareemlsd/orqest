"""``TableComponent`` — column-typed tabular data."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from orqest.ui.spec import UIComponentSpec

ColumnKind = Literal["text", "number", "date", "boolean", "link"]


class TableColumn(BaseModel):
    key: str
    """Row-dict key the renderer reads to populate this column."""
    label: str
    kind: ColumnKind = "text"
    sortable: bool = True


class TableComponentData(BaseModel):
    columns: list[TableColumn]
    rows: list[dict[str, Any]] = Field(default_factory=list)
    page_size: int = 50


class TableComponent(UIComponentSpec[TableComponentData]):
    component_type: Literal["table"] = "table"
    data: TableComponentData
