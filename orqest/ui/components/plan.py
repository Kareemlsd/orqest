"""``PlanComponent`` — wraps :class:`ExecutionPlan` task list.

The init payload is byte-identical to :meth:`ExecutionPlan.to_sse_init`
so existing Polymath-style frontends continue to work after migration.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from orqest.plan.execution_plan import PlanTask
from orqest.ui.spec import UIComponentSpec


class PlanComponentData(BaseModel):
    """Data payload — list of :class:`PlanTask` records."""

    tasks: list[PlanTask] = Field(default_factory=list)


class PlanComponent(UIComponentSpec[PlanComponentData]):
    component_type: Literal["plan"] = "plan"
    data: PlanComponentData
