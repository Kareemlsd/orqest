# Generative UI

Orqest lets agents emit typed component specifications that a frontend resolves dynamically. Instead of returning text for the UI to render, the agent emits a `UIComponentSpec[T]` (chart, table, form, plan, takeover dialog, Vega visualization, Mermaid diagram, sandboxed HTML, etc.). The frontend hot-loads a renderer keyed on `component_type`. Subsequent state changes flow as `UIDeltaEvent` records on the same SSE stream.

## What problem does this solve?

Agents that return prose and let the UI render it leave a lot of capability on the table. If the agent is analyzing data, you want a chart — not a paragraph describing one. If it needs your approval, you want a dialog — not "should I proceed? (yes/no)" in chat. The agent already knows the *shape* of the answer; let it pick the surface. Generative UI flips the protocol: the agent describes what to render, the frontend resolves how. Same backend produces a Plan, a chart, and a PDF report based on what the work needs.

## UIComponentSpec

Generic Pydantic with a `component_type` `Literal` discriminator. Each first-party component is a subclass that fixes `component_type` and types the `data: T` payload.

| Field | Type | Description |
|-------|------|-------------|
| `component_id` | `str` | Stable identifier (the frontend uses this to route deltas to the right instance) |
| `component_type` | `Literal["plan" \| "chart" \| ...]` | Discriminator the frontend resolves to a renderer |
| `data` | `T` (typed payload) | Component-specific payload — strongly typed per subclass |
| `metadata` | `dict[str, Any]` | Free-form (used for layout hints, accessibility, etc.) |
| `created_at` | `datetime` | UTC timestamp |

## UIDeltaEvent — partial updates

Once a component is initialized, you patch it with delta events. Avoids re-shipping the full payload on every change.

| Field | Type | Description |
|-------|------|-------------|
| `op` | `Literal["replace", "merge", "append", "remove"]` | The mutation kind |
| `path` | `str` | Dot-path into the `data` payload (e.g., `"series.0.points"`) |
| `value` | `Any` | New value (or to-merge object, or to-append item) |

Ops:
- `replace` — overwrite the value at `path`
- `merge` — shallow-merge `value` (object) into the dict at `path`
- `append` — append `value` to the list at `path`
- `remove` — delete the key/element at `path`

## Three layers of first-party components

Components ship in three layers — pick the lowest layer that does the job.

### Layer 1 — Compositional primitives

Hand-typed components for common UI patterns:

- `PlanComponent` — task list (carries `PlanTask` instances; ties into `ExecutionPlan`)
- `ChartComponent` — line / bar / scatter / pie / heatmap with typed `ChartSeries`
- `TableComponent` — typed `TableColumn` + rows
- `FormComponent` — typed `FormField` + submit event handle
- `TakeoverDialogComponent` — confirm / input / choice (the agent asks the user a question)
- `LayoutComponent`, `TextComponent`, `MarkdownComponent`, `ImageComponent`, `BadgeComponent`, `ButtonComponent`, `InputComponent`

### Layer 2 — Declarative grammars

When you need richer visualization than Layer 1 covers — pass a spec the frontend already knows how to render:

- `VegaChartComponent` — Vega-Lite spec passed through
- `MermaidComponent` — Mermaid diagram source
- `LatexComponent` — KaTeX/MathJax-renderable LaTeX
- `JsonViewerComponent` — collapsible JSON tree

### Layer 3 — Sandboxed escape hatch

For one-offs the framework can't anticipate:

- `SandboxedHTMLComponent` — HTML/CSS/JS in an iframe sandbox

## UIEmitter — convenience facade

The minimal API. Wraps an `EventBus` so init/delta/remove are one line each.

```python
import asyncio
from orqest.observability import EventBus
from orqest.ui import (
    ChartComponent,
    ChartComponentData,
    ChartSeries,
    UIEmitter,
)


async def main():
    bus = EventBus()
    emitter = UIEmitter(bus)

    # Initialize a chart
    chart = ChartComponent(
        component_id="latency-chart",
        data=ChartComponentData(
            kind="line",
            title="Request latency",
            x_label="time",
            y_label="ms",
            series=[
                ChartSeries(
                    name="p50",
                    points=[{"x": 0, "y": 12}, {"x": 1, "y": 14}],
                ),
            ],
        ),
    )
    emitter.init(chart)

    # Append a new point
    emitter.delta(
        component_id="latency-chart",
        op="append",
        path="series.0.points",
        value={"x": 2, "y": 18},
    )

    # Remove the chart entirely
    emitter.remove(component_id="latency-chart")


asyncio.run(main())
```

## Event-type conventions

The emitter maps to SSE event types via dedicated helpers. The frontend resolves a renderer by parsing the event type.

| Event type | When | Helper |
|------------|------|--------|
| `ui.<component_type>.init` | Component first appears | `ui_init_event_type(component_type)` |
| `ui.<component_type>.delta` | State patch | `ui_delta_event_type(component_type)` |
| `ui.<component_type>.remove` | Component dismissed | `ui_remove_event_type(component_type)` |

For `ChartComponent`: `ui.chart.init`, `ui.chart.delta`, `ui.chart.remove`.

## ComponentRegistry — per-Workbench, no module singleton

Each `Workbench` carries its own registry. This avoids the rigidity of module-level state and lets two consumers in the same process register different component sets.

```python
from orqest.ui import ComponentRegistry, default_registry, UIComponentSpec
from pydantic import BaseModel
from typing import Literal


# Define a custom component for your domain
class MoleculeViewerData(BaseModel):
    smiles: str
    color_by: Literal["element", "charge"] = "element"


class MoleculeViewerComponent(UIComponentSpec[MoleculeViewerData]):
    component_type: Literal["molecule_viewer"] = "molecule_viewer"
    data: MoleculeViewerData


# Build a registry that includes both first-party and your custom one
registry = default_registry()  # PlanComponent, ChartComponent, etc.
registry.register(MoleculeViewerComponent)
```

`Workbench(ui_registry=registry, auto_register_first_party_ui=True)` injects it.

## ExecutionPlan dual emission

`ExecutionPlan` opt-in flag-gates dual emission of legacy `plan.*` events alongside typed `ui.plan.*` events. Default off — existing emission-count assertions stay byte-identical.

```python
from orqest.plan import ExecutionPlan

plan = ExecutionPlan(...)
plan.enable_ui_events(component_id="plan")  # opt-in dual emission
```

## SSE sidecar — flushing to the frontend

`sse_sidecar(bus, ...)` is an async iterator yielding SSE-formatted strings. Plug into FastAPI / Starlette / aiohttp / etc. The frontend subscribes and resolves renderers by event type.

```python
from fastapi import FastAPI
from sse_starlette import EventSourceResponse
from orqest.observability import sse_sidecar

app = FastAPI()


@app.get("/sessions/{session_id}/events")
async def events(session_id: str):
    bus = get_bus_for(session_id)
    return EventSourceResponse(sse_sidecar(bus, replay=(), heartbeat_s=15.0))
```

## Custom component example — end to end

```python
import asyncio
from typing import Literal
from pydantic import BaseModel
from orqest.observability import EventBus
from orqest.ui import (
    ComponentRegistry,
    UIComponentSpec,
    UIEmitter,
    default_registry,
)


class RiskHeatmapData(BaseModel):
    rows: list[str]
    cols: list[str]
    cells: list[list[float]]  # 0 (low) → 1 (high)


class RiskHeatmapComponent(UIComponentSpec[RiskHeatmapData]):
    component_type: Literal["risk_heatmap"] = "risk_heatmap"
    data: RiskHeatmapData


async def main():
    registry = default_registry()
    registry.register(RiskHeatmapComponent)

    bus = EventBus()
    emitter = UIEmitter(bus)

    spec = RiskHeatmapComponent(
        component_id="q3-risk",
        data=RiskHeatmapData(
            rows=["EU", "US", "APAC"],
            cols=["liquidity", "credit", "operational"],
            cells=[[0.2, 0.4, 0.1], [0.3, 0.5, 0.2], [0.7, 0.6, 0.3]],
        ),
    )
    emitter.init(spec)
    # Emits an "ui.risk_heatmap.init" event on the bus.
    # The frontend (which previously registered a renderer for "risk_heatmap")
    # resolves and mounts it.


asyncio.run(main())
```

## Best practices

- **Start at the highest layer that fits.** `PlanComponent` over a custom component over `SandboxedHTMLComponent`. The frontend already knows how to render Layer 1 — you pay design surface for every layer below.
- **`component_id` is stable.** It's how deltas route. Using random UUIDs per-emit defeats the delta contract.
- **Deltas, not full re-emits.** A 50KB chart that gains one point should emit a `delta(append, "series.0.points", {x,y})`, not a fresh `init`.
- **Keep frontend renderers thin.** The component is a typed contract; the frontend just maps fields to DOM. Behavior belongs in the agent, not the renderer.
- **Don't reach into Layer 3 (`SandboxedHTMLComponent`) by default.** It's for one-offs that don't deserve a typed component. Frequent use is a smell — promote it to a typed component instead.

## Pitfalls

- **Don't share `ComponentRegistry` across consumers** that need different schemas. The per-Workbench design is intentional.
- **Don't emit `init` for the same `component_id` twice in a session** — that's a re-mount; the frontend may flicker. Use a `delta(replace, "", new_data)` instead, or `remove` then `init`.
- **Don't trust the frontend to validate.** The registry's `validate_payload` runs at the backend boundary; the frontend just renders.
- **`UIEmitter` never raises on bus failure** — it logs at DEBUG. If you need delivery guarantees, add a separate observability layer.
- **Polymath uses every layer of generative UI** because it's the substrate's flagship demo. Most consumer apps pick 2-3 components and stay there.

## What's happening under the hood

1. Agent computes a typed component (or accumulates one across tool calls)
2. `UIEmitter.init(spec)` emits `AgentEvent(event_type="ui.<type>.init", data=spec.model_dump())` on the `EventBus`
3. `sse_sidecar(bus, ...)` translates events to SSE frames; ring-buffered against slow consumers
4. Frontend's resolver parses the event type, finds the renderer, mounts the component
5. Subsequent `delta` events patch the component's `data` in place via dot-path navigation
6. `remove` event tears the component down

## Related Concepts

- [Workbench](workbench.md) — bundles `ComponentRegistry` + `EventBus`
- [Observability](observability.md) — the `EventBus` underneath everything
- [SSE Sidecar](sse-sidecar.md) — flushing events to the frontend
- [Execution Plan](execution-plan.md) — `PlanComponent` integration
- [Event Bus Hook](event-bus-publish-hook.md) — emits `tool.*` events alongside `ui.*`
