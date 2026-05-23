"""``UIComponentSpec[T]`` and ``UIDeltaEvent`` — the generative-UI protocol.

The agent emits a typed component spec (``ui.<type>.init`` event); the
frontend resolves the renderer by ``component_type`` and hot-loads it.
Subsequent state updates flow as :class:`UIDeltaEvent` records on
``ui.<type>.delta``.

Generic base + discriminator field (rather than a closed
:class:`Union`) keeps the protocol open: third-party consumers register
their own components without changing core. Pydantic's per-class
``Literal`` default on ``component_type`` enforces correctness on each
subclass; consumers' typed events round-trip cleanly through
``model_dump`` / ``model_validate``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T", bound=BaseModel)


class UIComponentSpec(BaseModel, Generic[T]):
    """Generic init payload for a frontend-renderable component.

    Subclasses MUST override ``component_type`` with a unique
    :class:`Literal` value so the frontend resolver can pick a renderer.
    The ``data`` field carries the typed payload the renderer reads.

    The schema is intentionally minimal: every concrete component
    inherits the same envelope (``component_type``, ``component_id``,
    ``data``, ``metadata``, ``created_at``) so the SSE protocol and the
    frontend resolver can be component-agnostic.
    """

    component_type: str = Field(description="Discriminator — frontend resolver key.")
    component_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Stable id for delta updates targeting this component.",
    )
    data: T
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC)
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_event_data(self) -> dict[str, Any]:
        """Serialize to the dict that lands inside :class:`AgentEvent.data`."""
        return self.model_dump(mode="json")


UIDeltaOp = Literal["replace", "merge", "append", "remove"]
"""Op set for partial component updates.

* ``replace`` — set value at ``path`` to ``value`` (RFC 6902 replace).
* ``merge``  — shallow-merge ``value`` (a dict) into the dict at ``path``;
  if value-at-path is not a dict, behaves like replace.
* ``append`` — append ``value`` to the list at ``path``. Required for
  streaming-append components (chart series, table rows).
* ``remove`` — delete the field/element at ``path``. ``value`` ignored.
"""


class UIDeltaEvent(BaseModel):
    """Targeted partial update to a previously-emitted :class:`UIComponentSpec`.

    ``path`` is a dot-path into ``data`` (root = empty string). For list
    operations, integer indices may appear in the path (e.g.
    ``"tasks.0.status"``). Frontend implementations apply the op
    against the previously-rendered component identified by
    ``component_id``; an unknown id should be treated as a no-op (the
    consumer can re-fetch via the snapshot endpoint to recover).
    """

    component_id: str
    component_type: str
    op: UIDeltaOp
    path: str = Field(default="", description='Dot-path; "" means the data root.')
    value: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_event_data(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
