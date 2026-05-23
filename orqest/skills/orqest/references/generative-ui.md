# Generative UI — reference

Compressed judgment layer over `orqest/ui/`. For full reference, read `docs/concepts/generative_ui.md`.

## The shape — `UIComponentSpec[T]`

Generic Pydantic with a `component_type` `Literal` discriminator. Each first-party component subclasses and fixes the discriminator + the typed `data: T`.

| Field | Type | Description |
|---|---|---|
| `component_id` | `str` | Stable identifier — the frontend uses this to route deltas to the right instance |
| `component_type` | `Literal["plan" \| "chart" \| ...]` | Discriminator the frontend resolves to a renderer |
| `data` | `T` (typed payload) | Component-specific payload — strongly typed per subclass |
| `metadata` | `dict` | Layout hints, accessibility, etc. |

## Three layers of first-party components — pick the lowest that fits

```python
from orqest.ui import (
    # Layer 1 — compositional primitives
    PlanComponent, ChartComponent, TableComponent, FormComponent, TakeoverDialogComponent,
    LayoutComponent, TextComponent, MarkdownComponent, ImageComponent, BadgeComponent,
    ButtonComponent, InputComponent,
    # Layer 2 — declarative grammars
    VegaChartComponent, MermaidComponent, LatexComponent, JsonViewerComponent,
    # Layer 3 — sandboxed escape hatch (use sparingly)
    SandboxedHTMLComponent,
)
```

| Layer | When |
|---|---|
| 1 — compositional | Most cases. The frontend already knows how to render these — zero design surface cost. |
| 2 — declarative grammar | When you need a Vega-Lite chart, Mermaid diagram, LaTeX, or JSON tree. Frontend renders the grammar, you ship the spec. |
| 3 — `SandboxedHTMLComponent` | One-offs the framework can't anticipate. Frequent use is a smell — promote to a typed component. |

## `UIEmitter` — the minimal API

Wraps an `EventBus`; init/delta/remove are one line each.

```python
from orqest.observability import EventBus
from orqest.ui import UIEmitter, ChartComponent, ChartComponentData, ChartSeries

bus = EventBus()
emitter = UIEmitter(bus)

# Initialize
chart = ChartComponent(
    component_id="latency-chart",
    data=ChartComponentData(
        kind="line",
        title="Request latency",
        x_label="time",
        y_label="ms",
        series=[ChartSeries(name="p50", points=[{"x": 0, "y": 12}, {"x": 1, "y": 14}])],
    ),
)
emitter.init(chart)                                            # emits ui.chart.init

# Partial update via delta
emitter.delta(
    component_id="latency-chart",
    op="append",                                               # or "replace" / "merge" / "remove"
    path="series.0.points",                                    # dot-path into data
    value={"x": 2, "y": 18},
)                                                              # emits ui.chart.delta

# Dismiss
emitter.remove(component_id="latency-chart")                   # emits ui.chart.remove
```

## `UIDeltaEvent` — partial updates

```python
from orqest.ui import UIDeltaEvent
```

| `op` | Effect |
|---|---|
| `replace` | Overwrite the value at `path` |
| `merge` | Shallow-merge `value` (object) into the dict at `path` |
| `append` | Append `value` to the list at `path` |
| `remove` | Delete the key/element at `path` |

## SSE event type conventions

The frontend resolves a renderer by parsing the event type.

```python
from orqest.ui import ui_init_event_type, ui_delta_event_type, ui_remove_event_type

ui_init_event_type("chart")     # → "ui.chart.init"
ui_delta_event_type("chart")    # → "ui.chart.delta"
ui_remove_event_type("chart")   # → "ui.chart.remove"
```

Consumers should use the helpers, not hardcoded strings — keeps the frontend decoupled from event-name literals.

## `ComponentRegistry` — per-`Workbench`, no module singleton

Each `Workbench` carries its own registry. Two consumers in one process can register different component sets without colliding.

```python
from orqest.ui import ComponentRegistry, default_registry, UIComponentSpec
from pydantic import BaseModel
from typing import Literal

class MoleculeViewerData(BaseModel):
    smiles: str
    color_by: Literal["element", "charge"] = "element"

class MoleculeViewerComponent(UIComponentSpec[MoleculeViewerData]):
    component_type: Literal["molecule_viewer"] = "molecule_viewer"
    data: MoleculeViewerData

registry = default_registry()                                  # 17 first-party components
registry.register(MoleculeViewerComponent)

# Wire into Workbench
wb = Workbench(ui_registry=registry, auto_register_first_party_ui=True)
```

## `ExecutionPlan` dual emission

`ExecutionPlan` opt-in dual emission of legacy `plan.*` events + typed `ui.plan.*` events. Default off — existing emission-count assertions stay byte-identical.

```python
from orqest.plan import ExecutionPlan

plan = ExecutionPlan(...)
plan.enable_ui_events(component_id="plan")                     # opt-in
plan.as_component()                                            # → PlanComponent
```

## SSE sidecar — flushing to the frontend

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

`sse_sidecar` is ring-buffered against slow consumers; supports historical replay for reconnection.

## Pitfalls

- **Start at the highest layer that fits.** `PlanComponent` over a custom component over `SandboxedHTMLComponent`. Layer 1 is free design surface — you pay for everything below.
- **`component_id` is stable.** It's how deltas route. Random UUIDs per-emit defeats the delta contract.
- **Deltas, not full re-emits.** A 50KB chart that gains one point should emit `delta(append, "series.0.points", {x,y})`, not a fresh `init`.
- **Don't emit `init` twice for the same `component_id`.** That's a re-mount; the frontend may flicker. Use `delta(replace, "", new_data)`, or `remove` then `init`.
- **Don't trust the frontend to validate.** `registry.validate_payload` runs at the backend boundary; the frontend just renders.
- **`UIEmitter` never raises on bus failure.** It logs at DEBUG. For delivery guarantees, add a separate observability layer.
- **Don't share `ComponentRegistry` across consumers that need different schemas.** The per-Workbench design is intentional.
- **Behavior belongs in the agent, not the renderer.** The component is a typed contract; the frontend just maps fields to DOM. If the renderer is doing logic, the contract is too thin.

## Where to read more

- `docs/concepts/generative_ui.md` — full reference (incl. all 17 first-party components, payload schemas, custom-component end-to-end)
- `docs/concepts/sse-sidecar.md` — SSE flushing details
- `docs/concepts/execution-plan.md` — `PlanComponent` integration
- `docs/concepts/observability.md` — `EventBus` semantics
- `notebooks/03_generative_ui.ipynb` — agents emit `PlanComponent`, `TableComponent`, `ChartComponent` onto an `EventBus`; `sse_sidecar` streams to a frontend
