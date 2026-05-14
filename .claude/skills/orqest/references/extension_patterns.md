# Extending Orqest Itself

Most consumer apps use Orqest as-is. But occasionally a consumer needs a primitive Orqest doesn't ship — a new Watchdog (cost detector, schema-violation detector), a new memory backend (pgvector, Pinecone), a new ConfidenceProtocol (domain-specific), a custom UI component (MoleculeViewer, RiskHeatmap). This file maps each extension point to the canonical pattern.

> **First, ask: does this belong in the consumer or in core?**
> Litmus test: *"Could a developer building a headless coding assistant use this without knowing what Polymath is?"*
> If NO → consumer-only (a private subclass / hook / component in your project).
> If YES → propose upstream as an Orqest contribution.

## 2.1 New orchestration primitive

When `Pipeline` / `Parallel` / `Router` / `RefinementLoop` don't fit (e.g., a saga, a fan-out-merge-with-stragglers, a streaming join).

**Pattern:** mirror `Pipeline`. Reference: `orqest/orchestration/pipeline.py`.

1. Create `<your-project>/orchestration/<name>.py` (or in core: `orqest/orchestration/<name>.py`)
2. Generic over `[InputT, OutputT]`; reuse the existing `Step` Protocol; auto-coerce children via `_coerce_step`
3. Honor `HookDecision` (Continue/Skip/Redirect/Abort) at every compound boundary; `run_with_retry` is the cleanest precedent
4. Emit lifecycle events on the `EventBus` if your primitive has phases worth observing (`<your_name>.start`, `<your_name>.complete`)
5. Tests under `tests/orchestration/test_<name>.py`. Use `TestModel`.

## 2.2 New memory backend

When `LocalMemoryStore` (SQLite + FTS5) won't scale — pgvector, Pinecone, Qdrant, etc.

**Pattern:** implement `MemoryStore` Protocol. Reference: `orqest/memory/store.py`.

1. Implement `MemoryStore` Protocol — `store`, `recall`, `forget`, `update_reliability`, `count`
2. **Don't rewrite strategies.** Reuse the per-kind `RetrievalStrategy` Protocol from `orqest/memory/strategies.py`. Your backend dispatches to a strategy based on `memory_type`.
3. Best-effort error handling: log via `loguru`, never raise to the caller. Memory must never block an agent.
4. Backend-specific config: extend `MemoryConfig` (or subclass).
5. Tests under `tests/memory/test_<backend>.py`; mirror `test_local_memory_store.py`.

## 2.3 New ConfidenceProtocol

When the three shipped (`StructuredOutputProtocol`, `LLMSelfRatingProtocol`, `EnsembleProtocol`) don't fit — e.g., a domain-specific calibrated scorer, or an external rater service.

**Pattern:** implement `ConfidenceProtocol` Protocol. Reference: `orqest/metacognition/protocol.py`.

1. Implement `async score(output, state) -> tuple[float | None, list[str], bool, dict]`
2. Wire as the agent-level default via `BaseAgent(confidence_protocol=...)` or per-call via `run_enriched(..., confidence_protocol=...)`
3. Failures must surface as `confidence=None` with `metadata["protocol_error"]` — never raise. Best-effort.
4. Tests under `tests/metacognition/test_<protocol>.py`. Use `TestModel` for any LLM calls.

## 2.4 New Watchdog

When `Stall` / `Loop` / `Regression` don't catch a failure mode — e.g., schema-violation rate, cost-per-turn detector, repeated-error-class detector.

**Pattern:** implement `Watchdog` Protocol. Reference: `orqest/healing/watchdog.py`.

1. Implement `subscribe(bus)` and `signal() -> Detection | None`
2. Subscribe to relevant `EventBus` events in `subscribe`. Buffer state in an internal sliding window or counter.
3. `signal()` returns a fresh `Detection(detector="<name>", severity=…, summary=…, attributes=…)` on detection or `None` otherwise. Suppress double-fire.
4. Pass to `HealingRunner(watchdogs=[...])` or `WatchdogHook(watchdogs=[...])`
5. Extend `default_policy` (or pass a custom policy) to map `detection.detector == "<name>"` to a sensible `RecoveryAction`. Default to `AbortRun` if unsure.
6. Tests under `tests/healing/test_<name>_detector.py`; mirror `test_stall.py`.

## 2.5 New RecoveryAction

When the existing 5 actions don't cover an intent — e.g., `EscalateToOps` (Slack handoff), `PauseAndAlert` (set a checkpoint, page on-call).

**Pattern:** extend the discriminated union in `orqest/healing/recovery.py`.

```python
class EscalateToOps(_RecoveryBase):
    kind: Literal["escalate_ops"] = "escalate_ops"
    channel: str
    severity: Literal["warning", "page"] = "warning"
```

1. Add the new union member with a `kind: Literal[...]` discriminator
2. Extend the `RecoveryAction` union type alias
3. Extend `_action_to_decision` to translate to `HookDecision` (typically `Skip(stub_result=...)` or `Abort(reason=...)`)
4. Optionally extend `default_policy` so a specific `Detection.detector` maps to your new action
5. Tests in `tests/healing/test_recovery.py` cover the round-trip (Detection → action → HookDecision)

## 2.6 New UIComponentSpec

The most-extended pattern in real consumers. **Open extension point — no Orqest core change required for new component types.**

**Pattern:** subclass `UIComponentSpec[T]` + register on the consumer's `ComponentRegistry`.

```python
from typing import Literal
from pydantic import BaseModel
from orqest.ui import UIComponentSpec, ComponentRegistry, default_registry


class MoleculeViewerData(BaseModel):
    smiles: str
    color_by: Literal["element", "charge"] = "element"


class MoleculeViewerComponent(UIComponentSpec[MoleculeViewerData]):
    component_type: Literal["molecule_viewer"] = "molecule_viewer"
    data: MoleculeViewerData


registry = default_registry()       # pre-loads first-party
registry.register(MoleculeViewerComponent)
```

1. Subclass `UIComponentSpec[T]` with a typed `data: T`
2. Declare `component_type: Literal["molecule_viewer"]`
3. Register on the consumer's `ComponentRegistry` (per-Workbench)
4. The frontend resolves via `ui.molecule_viewer.{init,delta,remove}` event-type convention. Frontend must know how to render `component_type="molecule_viewer"`.
5. **First-party** components (broadly useful) live under `orqest/ui/components/` and are pre-loaded via `default_registry()`. Don't ship a domain-specific component as first-party.
6. Tests in `tests/ui/test_<component>.py`; cover serialization round-trip + delta-op application

## 2.7 New MCP discovery source / permission gate

The existing flow (`MCPDiscovery.search` + `ToolRegistry.get_or_discover` + `DiscoveryHook` + `PermissionGate`) covers online registry, well-known manifests, and web fallback.

**Pattern:** implement `PermissionGate` Protocol if your gate is novel. Reference: `orqest/mcp/permission.py`.

1. Implement `async allow(self, tool_name: str) -> bool`
2. Pass to `ToolRegistry.get_or_discover(..., permission=YourGate(), ...)` or `DiscoveryHook(..., permission=...)`
3. Audit-log emission flows through existing `discovery.requested` / `.connected` / `.denied` / `.failed` events on the bus — no new event types needed
4. Tests in `tests/mcp/test_<source>.py`

## 2.8 New ToolSandbox backend (latent — not yet shipped)

The `ToolSandbox` Protocol is the seam for safe execution of dynamic tool code. When the subpackage ships:

**Pattern:** implement `ToolSandbox` Protocol.

1. `async validate(code, allowed_imports)` — pure analysis
2. `async execute(code, args, allowed_imports, timeout_s, memory_mb)` — sandboxed execution
3. `__aenter__` / `__aexit__` — lifecycle
4. Default impl: `RestrictedPythonSandbox` (in-process, AST-based static restriction)
5. Third parties ship `DockerSandbox` / `FirecrackerSandbox` / `WasmSandbox`
6. Default-deny posture: empty `allowed_imports` rejects the spec at validate time
7. Tests in `tests/sandbox/test_<backend>.py`; cover safe arithmetic + every refused-pattern (import os, open, exec, dunder access)

## 2.9 New first-party tool

Domain-agnostic functions under `orqest.tools`. **Anything domain-specific belongs in the consumer.**

**Pattern:** Pydantic-AI `Tool`-shaped function.

1. Create `orqest/tools/<name>.py` with one or more `async def` functions returning typed Pydantic responses
2. Lazy registration — no module-level state. Consumer imports via `from orqest.tools.<name> import <fn>`.
3. Graceful degradation: if the tool needs an API key and it's missing, return a typed `<Name>Response(disabled_reason="...")` rather than raising. Mirrors `web_search` shape.
4. Tests in `tests/tools/test_<name>.py`. Mock the network/IO layer.

## 2.10 New EventBus event type

The bus is open — no registration required.

**Pattern:** follow the naming convention `<subsystem>.<event>[.<detail>]`.

Examples:
- `tool.before` / `tool.after` / `tool.error`
- `metacognition.confidence`
- `healing.detection` / `.action` / `.model_fallback` / `.model_chain_exhausted`
- `ui.<component_type>.{init,delta,remove}`
- `discovery.{requested,connected,denied,failed}`
- `plan.init`, `plan.task.updated`

1. Pick a name following the convention
2. Document the event type and its payload schema in the relevant concept doc
3. Emit via `bus.emit(AgentEvent(event_type="<name>", agent_name="…", data={…}, span_id=…, trace_id=…))`. Failures in handlers are logged and discarded.
4. If a watchdog or hook should subscribe, extend the relevant module per Section 2.4 / 2.5.

## When NOT to add to core

The litmus test, verbatim:

> *"Core Orqest manages the shape and flow of intelligence; extensions manage the matter and action of the domain. Could a developer building a headless coding assistant use this without knowing what Polymath is?"*

Examples that belong in **consumers**, not core:

- **Polymath's TakeoverDialog rendering.** The `TakeoverDialogComponent` *spec* is core (shape); the modal styling, confirm/input/choice handling are consumer (matter).
- **A domain-specific tool registry** (e.g., a CFD simulation harness, a clinical-decision-support harness, a financial-trading harness). `ToolRegistry` is core; the consumer's domain-specific tools live in the consumer.
- **OTel exporter.** `EventBus` + `AgentEvent` are core (shape); the OTel adapter that subscribes to the bus and forwards spans/metrics is a third-party `orqest-otel-exporter` package (matter).
- **Durable execution / workflow engine.** Orqest is explicitly **not** a workflow engine. Persistence of agent runs across crashes belongs in a consumer that wants that resilience cost — not in core.
- **Eval harness.** Metrics, replay, golden trajectories are observability tools, not cognitive primitives. Belongs in `orqest.eval` as a separate package, not in core.
- **Production memory backends (pgvector, Pinecone, Qdrant).** The `MemoryStore` Protocol is core (shape); concrete network-backed implementations are extensions or third-party packages.

When in doubt, apply the litmus test. If the feature would force a consumer in a different domain to learn yours to use Orqest, the feature belongs in a consumer.
