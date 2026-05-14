# Architecture — Extensibility Playbook

> **This file is the extensibility playbook for Orqest contributors.** It explains how each component plugs in, so adding a new orchestration primitive / memory backend / watchdog / confidence protocol / UI component / sandbox backend is a 30-minute task, not a week.
>
> For agent-instructions ground truth, see [`CLAUDE.md`](../CLAUDE.md).
> For library-consumer guidance, see [`SKILLS.md`](../SKILLS.md).
> For Pragmatic Programmer rules this codebase follows, see [`PRINCIPLES.md`](PRINCIPLES.md).

## Section 1 — Module Dependency Map

```
orqest/
├── __init__.py              → re-exports the slim facade (Workbench, Pipeline, ...)
├── config.py                → OrqestConfig + load_config (no internal deps)
├── hooks.py                 → HookRunner + ToolHook + HookDecision (loguru only)
│
├── agents/                  → Agent primitives
│   ├── base_agent.py        → state, context_manager, llm_model, load_sys_prompt
│   ├── state.py             → GlobalState (pydantic only)
│   ├── session_state.py     → state (extends GlobalState)
│   ├── compound_tool.py     → base_agent, hooks
│   ├── context_manager.py   → token_counter, metacognition.salience (optional)
│   ├── retry.py             → base_agent, hooks
│   └── tool_wrapper.py      → base_agent, state
│
├── orchestration/           → Composition primitives
│   ├── types.py             → ErrorStrategy, StepConfig, PipelineEvent
│   ├── step.py              → Step protocol, AgentStep, FunctionStep, _coerce_step
│   ├── pipeline.py          → step, types
│   ├── parallel.py          → step
│   ├── router.py            → step, state, base_agent
│   └── loop.py              → step, base_agent, metacognition (optional)
│
├── memory/                  → Cognitive memory typology
│   ├── store.py             → MemoryStore protocol, MemoryEntry, MemoryFilter, Skill
│   ├── local.py             → store (LocalMemoryStore SQLite + FTS5)
│   ├── strategies.py        → SemanticStrategy, EpisodicStrategy, ProceduralStrategy
│   └── config.py            → MemoryConfig + PerKindConfig (frozen dataclass)
│
├── autonomy/                → Runtime agent spawning (Phase 3)
│   ├── spec.py              → AgentSpec, ToolSpec
│   ├── factory.py           → AgentFactory → DynamicAgent (pydantic.create_model)
│   ├── registry.py          → ToolRegistry (register/get/search/get_or_discover)
│   └── meta.py              → MetaOrchestrator (goal → decompose → spawn → execute)
│
├── observability/           → Phase 4 (events, traces, SSE)
│   ├── tracer.py            → Span, Tracer protocol, JSONTracer
│   ├── events.py            → AgentEvent, EventBus
│   ├── event_bus_hook.py    → EventBusPublishHook
│   └── sse_sidecar.py       → SSE iterator with replay + heartbeat + ring buffer
│
├── workbench/               → Runtime container
│   └── workbench.py         → memory + tracer + bus + ui_registry + recent_events
│
├── compound/                → New-style compound tool (Phase 1c)
│   └── sub_agent_tool.py    → SubAgentTool[StateT, ResultT] + SubAgentResult
│
├── plan/                    → Multi-step workflow tracking
│   └── execution_plan.py    → ExecutionPlan, PlanTask (byte-stable to_sse_init)
│
├── mcp/                     → Phase 5 (client + server + auto-wire)
│   ├── config.py            → MCPServerConfig, MCPConfig
│   ├── client.py            → MCPConnection, MCPServerManager
│   ├── adapter.py           → MCPToolAdapter (MCP tool defs → pydantic-ai Tool)
│   ├── discovery.py         → MCPDiscovery, DiscoveredServer
│   ├── discovery_hook.py    → DiscoveryHook (auto-register on tool-not-found)
│   ├── permission.py        → PermissionGate Protocol + AllowAll/DenyAll/AllowList
│   └── server.py            → create_orqest_server (FastMCP)
│
├── metacognition/           → Vision feature #3 (Wave 1.3)
│   ├── enriched.py          → EnrichedOutput[OutputT]
│   ├── protocol.py          → ConfidenceProtocol + StructuredOutput/LLMSelfRating/Ensemble
│   ├── hook.py              → MetacognitionHook (ToolHook → metacognition.confidence)
│   ├── salience.py          → confidence_salience / recency_salience
│   └── config.py            → MetacognitionConfig
│
├── healing/                 → Vision feature #4 (Wave 2)
│   ├── watchdog.py          → Watchdog Protocol + Detection
│   ├── stall.py             → StallDetector
│   ├── loop.py              → LoopDetector
│   ├── regression.py        → RegressionDetector (consumes metacognition.confidence)
│   ├── recovery.py          → RecoveryAction + WatchdogHook + default_policy
│   ├── fallback.py          → FallbackModel (subclass of pydantic_ai.models.Model)
│   ├── runner.py            → HealingRunner (async context manager)
│   └── config.py            → HealingConfig
│
├── ui/                      → Vision feature #5 (Wave 3)
│   ├── spec.py              → UIComponentSpec[T] + UIDeltaEvent
│   ├── registry.py          → ComponentRegistry per-Workbench
│   ├── emitter.py           → UIEmitter (init/delta/remove)
│   ├── events.py            → ui_init/delta/remove_event_type helpers
│   └── components/          → 17 first-party components across 3 layers
│
├── tools/
│   └── web.py               → web_search, web_fetch (multi-provider, graceful)
│
├── utils/
│   ├── llm_model.py         → resolve_model (lazy provider imports)
│   └── token_counter.py     → estimate_tokens (3.5 chars/token heuristic)
│
└── io_utils/
    └── load_sys_prompt.py   → upward search for system_prompts/
```

### Cross-feature handshake — the load-bearing edge

The most distinctive integration in the substrate: **`metacognition` produces the signal; `healing` acts on it.**

```
  agent.run_enriched(...)
      ↓ produces EnrichedOutput
  MetacognitionHook → emits "metacognition.confidence" event
      ↓ on EventBus
  RegressionDetector → buffers events, signals Detection on drop
      ↓
  policy → returns RecoveryAction (default: AbortRun)
      ↓
  WatchdogHook → translates to HookDecision (Abort)
      ↓
  HookRunner → CompoundTool.run honors decision → halts the flow
```

Wire metacognition without healing: events fire, nobody listens (no-op).
Wire healing without metacognition: `RegressionDetector` no-ops gracefully; stall/loop still work.
Each piece degrades cleanly. **Don't break this property when extending.**

---

## Section 2 — Extension Patterns

This is the core of this document. Each subsection names a canonical pattern for adding a new component. Mirror it; tests pass; the substrate stays orthogonal.

### 2.1 Adding a new orchestration primitive

When the existing `Pipeline` / `Parallel` / `Router` / `RefinementLoop` don't fit a composition pattern (e.g., a saga, a fan-out-merge-with-stragglers, a streaming join). Reference: `orqest/orchestration/pipeline.py`.

1. Create `orqest/orchestration/<name>.py`
2. Define a Pydantic state model in `types.py` if needed (otherwise reuse existing)
3. Implement the runtime class — generic `[InputT, OutputT]` over the existing `Step` protocol; auto-coerce children via `_coerce_step`
4. Honor `HookDecision` (Continue/Skip/Redirect/Abort) at every compound boundary; `run_with_retry` is the cleanest precedent
5. Emit lifecycle events on the EventBus if your primitive has phases worth observing (`<your_name>.start`, `<your_name>.complete`)
6. Tests under `tests/orchestration/test_<name>.py`. Use `TestModel` from pydantic-ai for agent step inputs.
7. Re-export from `orqest/orchestration/__init__.py`; add to root `__all__` only if it's a facade type
8. Concept doc at `docs/concepts/<name>.md` (use `memory.md` as the template)
9. Wire into `mkdocs.yml` nav

### 2.2 Adding a new memory backend

When `LocalMemoryStore` (SQLite + FTS5) won't scale — pgvector, Pinecone, Qdrant, etc.

1. Implement `MemoryStore` Protocol from `orqest/memory/store.py` (`store`, `recall`, `forget`, `update_reliability`, `count`)
2. **Don't rewrite strategies.** Reuse the per-kind `RetrievalStrategy` Protocol from `strategies.py`. Your backend dispatches to a strategy based on `memory_type`.
3. Best-effort error handling: log failures via `loguru`, never raise to the caller. Memory must never block an agent.
4. Tests under `tests/memory/test_<backend>.py`; mirror `test_local_memory_store.py`'s shape
5. Backend-specific config: extend `MemoryConfig` (or subclass). Fields like connection string / API key live there.
6. No new dependency creep: optional extras in `pyproject.toml` (`[project.optional-dependencies] memory_pgvector = ["psycopg[binary]>=3"]`)
7. Document in `docs/concepts/memory.md` under "Pluggable backends"

### 2.3 Adding a new ConfidenceProtocol

When the three shipped (`StructuredOutputProtocol`, `LLMSelfRatingProtocol`, `EnsembleProtocol`) don't fit — e.g., a domain-specific calibrated scorer, or an external rater.

1. Implement `ConfidenceProtocol` Protocol from `orqest/metacognition/protocol.py` (`async score(output, state) -> tuple[float | None, list[str], bool, dict]`)
2. Wire as the agent-level default via `BaseAgent(confidence_protocol=...)` or per-call via `run_enriched(..., confidence_protocol=...)`
3. Failures must surface as `confidence=None` with `metadata["protocol_error"]` — never raise. Best-effort.
4. Tests under `tests/metacognition/test_<protocol>.py`. Use `TestModel` for any LLM calls.
5. Re-export from `orqest/metacognition/__init__.py` only if it's first-party general-purpose; consumer-specific protocols stay in the consumer.

### 2.4 Adding a new Watchdog

When `Stall` / `Loop` / `Regression` don't catch a failure mode — e.g., schema-violation rate, cost-per-turn detector, repeated-error-class detector.

1. Implement `Watchdog` Protocol from `orqest/healing/watchdog.py` (`subscribe(bus)`, `signal() -> Detection | None`)
2. Subscribe to the relevant `EventBus` events in `subscribe`. Buffer state in an internal sliding window or counter.
3. `signal()` returns a fresh `Detection(detector="<name>", severity=…, summary=…, attributes=…)` on detection or `None` otherwise. Suppress double-fire.
4. Pass to `HealingRunner(watchdogs=[...])` or `WatchdogHook(watchdogs=[...])`
5. Extend `default_policy` in `recovery.py` to map `detection.detector == "<name>"` to a sensible `RecoveryAction` (default to `AbortRun` if unsure)
6. Tests under `tests/healing/test_<name>_detector.py`; mirror `test_stall.py`
7. Document in `docs/concepts/healing.md` under "Watchdogs"

### 2.5 Adding a new RecoveryAction

When the existing actions (`EscalateToUser` / `AbortRun`) don't cover an intent — e.g., `EscalateToOps` (Slack handoff), `PauseAndAlert` (set a checkpoint, page on-call).

1. Add a new union member in `orqest/healing/recovery.py`:
   ```python
   class EscalateToOps(_RecoveryBase):
       kind: Literal["escalate_ops"] = "escalate_ops"
       channel: str
       severity: Literal["warning", "page"] = "warning"
   ```
2. Extend the `RecoveryAction` union
3. Extend `_action_to_decision` to translate the new action to a `HookDecision` (typically `Skip(reason=…, stub_result=…)` or `Abort(reason=…)`)
4. Optionally extend `default_policy` so a specific `Detection.detector` maps to your new action
5. Tests in `tests/healing/test_recovery.py` cover the round-trip (Detection → action → HookDecision)
6. Re-export from `orqest/healing/__init__.py`

### 2.6 Adding a new UIComponentSpec

The most-extended pattern in real consumers (MoleculeViewer, RiskHeatmap, OrgChart, etc.). Open extension point — **no Orqest core change required for new component types** (matches the registry pattern).

1. Subclass `UIComponentSpec[T]` with a typed `data: T`:
   ```python
   from typing import Literal
   from pydantic import BaseModel
   from orqest.ui import UIComponentSpec

   class MoleculeViewerData(BaseModel):
       smiles: str
       color_by: Literal["element", "charge"] = "element"

   class MoleculeViewerComponent(UIComponentSpec[MoleculeViewerData]):
       component_type: Literal["molecule_viewer"] = "molecule_viewer"
       data: MoleculeViewerData
   ```
2. Register on the consumer's `ComponentRegistry`:
   ```python
   registry.register(MoleculeViewerComponent)
   ```
3. The frontend resolves via the `ui.molecule_viewer.{init,delta,remove}` event-type convention. Frontend must know how to render `component_type="molecule_viewer"`.
4. **First-party** components (those that ship in core because they're broadly useful) live under `orqest/ui/components/` and are pre-loaded via `default_registry()`. Don't ship a domain-specific component as first-party.
5. Tests in `tests/ui/test_<component>.py`; cover serialization round-trip + delta-op application

### 2.7 Adding a new MCP discovery source / permission gate

The existing discovery flow (`MCPDiscovery.search` + `ToolRegistry.get_or_discover` + `DiscoveryHook` + `PermissionGate`) covers online registry, well-known manifests, and web fallback. Add a new discovery source by:

1. Implement `PermissionGate` Protocol from `orqest/mcp/permission.py` if your gate is novel
2. Pass the gate to `ToolRegistry.get_or_discover(..., permission=YourGate(), ...)`
3. Audit-log emission flows through existing `discovery.requested` / `.connected` / `.denied` / `.failed` events on the bus — no new event types needed
4. Tests in `tests/mcp/test_<source>.py`

### 2.8 Adding a new ToolSandbox backend (latent — when sandbox subpackage lands)

The `ToolSandbox` Protocol is the seam for safe execution of dynamic tool code. When the subpackage ships, this pattern applies:

1. Implement the `ToolSandbox` Protocol (`async validate(code, allowed_imports)`, `async execute(code, args, allowed_imports, timeout_s, memory_mb)`, `__aenter__`/`__aexit__`)
2. Pluggable backends — the default is `RestrictedPythonSandbox` (in-process, AST-based static restriction); third parties ship `DockerSandbox` / `FirecrackerSandbox` / `WasmSandbox`
3. Default-deny posture: empty `allowed_imports` rejects the spec at validate time
4. Pass to `DynamicToolFactory(sandbox=YourSandbox(), permission=...)`
5. Tests in `tests/sandbox/test_<backend>.py`; cover safe arithmetic + every refused-pattern (import os, open, exec, dunder access)

### 2.9 Adding a new first-party tool

Drop a Pydantic-AI `Tool`-shaped function under `orqest/tools/`. Keep it domain-agnostic — anything domain-specific belongs in the consumer.

1. Create `orqest/tools/<name>.py` with one or more async functions returning typed Pydantic responses
2. Register lazily — no module-level state. Consumer imports via `from orqest.tools.<name> import <fn>`.
3. Graceful degradation: if the tool needs an API key and it's missing, return a typed `<Name>Response(disabled_reason="...")` rather than raising. Mirrors `web_search` shape.
4. Tests in `tests/tools/test_<name>.py`. Mock the network/IO layer.
5. Document in `docs/concepts/web-tools.md` (or a new concept doc if it warrants one)

### 2.10 Adding a new event type to the EventBus

The bus is open — no registration required. Convention: `<subsystem>.<event>[.<detail>]`.

1. Pick a name following the convention. Examples: `tool.before` / `tool.after` / `tool.error`, `metacognition.confidence`, `healing.detection` / `.action` / `.model_fallback` / `.model_chain_exhausted`, `ui.<component_type>.{init,delta,remove}`, `discovery.{requested,connected,denied,failed}`, `plan.init`, `plan.task.updated`
2. Document the new event type and its payload schema in the relevant concept doc
3. Emit via `bus.emit(AgentEvent(event_type="<name>", agent_name="…", data={…}, span_id=…, trace_id=…))`. Failures in handlers are logged and discarded.
4. If a watchdog or hook should subscribe to it, extend the relevant module per Section 2.4 / 2.5

---

## Section 3 — Cross-cutting Conventions

Apply universally. If your contribution violates one of these, expect review pushback.

- **Async-first.** Every agent path is `async def`. Bridge to sync only at framework boundaries (CLI, sync HTTP handlers). Counter-example: a `def call_model()` defeats every downstream caller.
- **Pydantic for state and contracts.** Inputs, outputs, memory entries, plan tasks, component specs — all Pydantic. Counter-example: passing a `dict` as `state` couples consumers to internal field names.
- **Frozen dataclass for config.** Immutable at runtime; validated in `__post_init__`. Pydantic on configs is overhead — they're constructed once at startup.
- **Generic typing.** `BaseAgent[StateT, OutputT]`, `Pipeline[InputT, OutputT]`, `SubAgentTool[StateT, ResultT]`. Always parameterized. Counter-example: `Pipeline` returning `Any` defeats the type chain.
- **Constructor injection. No module-level state.** Workbench / EventBus / Tracer / Registry are per-session. Counter-example: a module-level `default_bus = EventBus()` leaks subscribers across consumers.
- **Fire-and-forget hooks.** `HookRunner._safe_call` wraps in try/except, logs at WARNING, never propagates. Counter-example: a hook that raises kills the agent run.
- **Best-effort memory + UI emit.** `LocalMemoryStore` swallows SQLite errors and logs. `UIEmitter.init/delta/remove` log at DEBUG on bus failure. Counter-example: memory raising on an FTS5 quirk breaks an unrelated agent run.
- **Pydantic discriminated unions** for `kind:Literal[...]` shapes (HookDecision, RecoveryAction, UIComponentSpec). Counter-example: bare unions without a discriminator force runtime `isinstance` checks at every call site.
- **Lazy provider imports.** SDK imports go inside `resolve_model()` so users only need the SDK for their chosen provider. Counter-example: top-level `import openai` forces all users to install OpenAI's SDK.
- **One level of inheritance.** `BaseAgent → ConcreteAgent` is fine. Beyond that, prefer Protocols + composition. Counter-example: a 4-level abstract hierarchy where `ConcreteAgent ← Refined ← Async ← Cached ← BaseAgent` is unreadable.
- **Tracer bullets.** Land the smallest end-to-end working slice first; iterate from there. Counter-example: designing the full `MetaOrchestrator` API in isolation before two real agents exchange a goal.
- **Crash early.** Validate at construction; trust internally. Counter-example: a tool that silently returns `None` when its API key is unset.

---

## Section 4 — Test Layout Mirroring

- Test files mirror source layout under `tests/`. `orqest/healing/runner.py` → `tests/healing/test_runner.py`.
- Use `TestModel` from `pydantic-ai.models.test`. Never require real API keys for the CI-blocking suite.
- Integration tests cross subsystems explicitly — `tests/healing/test_runner_with_metacognition.py` is allowed and useful.
- pytest-asyncio for async tests; default `asyncio_mode = "auto"` in `pyproject.toml`.
- Property tests via `hypothesis` are encouraged for spec serialization round-trips.
- Fixtures live in `tests/conftest.py` (`test_config`, `test_model`, etc.).
- Every routing/dispatch branch gets an explicit test. No "if branches without tests" — that's a Pragmatic violation.

---

## Section 5 — Public API Discipline

- Only **facade types** re-export from `orqest/__init__.py`. The current 18-symbol surface (Workbench, Pipeline, Parallel, Router, RefinementLoop, ExecutionPlan + Plan types, EnrichedOutput, MetacognitionConfig, HealingConfig, HookRunner + HookDecision variants, OrqestConfig + load_config + get_default_config).
- Subsystem-specific types live in their submodule's `__all__`. Consumers import via `from orqest.<subsystem> import <symbol>` per the documented submodule paths.
- New subpackages add their own `__init__.py` with `__all__`. Don't dump everything into root.
- Internal helpers stay private (`_leading_underscore`). Counter-example: re-exporting `_coerce_step` makes it a public contract by accident.

---

## Section 6 — Where Things Live (Compressed Map)

| Concern | Location |
|---------|----------|
| Agent definition | `orqest.agents.BaseAgent` |
| Conversation state | `orqest.agents.GlobalState` / `BaseSessionState` |
| History truncation | `orqest.agents.context_manager.ContextManager` |
| Multi-step composition | `orqest.orchestration.{Pipeline,Parallel,Router,RefinementLoop}` |
| Lifecycle hooks | `orqest.hooks.{HookRunner,ToolHook,HookDecision}` |
| Compound tool wrap | `orqest.compound.SubAgentTool` |
| Memory persistence | `orqest.memory.{MemoryStore,LocalMemoryStore}` |
| Memory typology | `orqest.memory.strategies.{Semantic,Episodic,Procedural}Strategy` |
| Runtime agent design | `orqest.autonomy.{AgentSpec,AgentFactory,MetaOrchestrator}` |
| Tool registry | `orqest.autonomy.ToolRegistry` |
| Tracing | `orqest.observability.{Span,Tracer,JSONTracer}` |
| Event bus | `orqest.observability.EventBus` + `EventBusPublishHook` |
| SSE streaming | `orqest.observability.sse_sidecar` |
| MCP client | `orqest.mcp.{MCPServerManager,MCPConnection}` |
| MCP discovery | `orqest.mcp.{MCPDiscovery,DiscoveryHook,PermissionGate}` |
| MCP server | `orqest.mcp.create_orqest_server` |
| Confidence | `orqest.metacognition.{EnrichedOutput,ConfidenceProtocol,*Protocol}` |
| Cognitive hooks | `orqest.metacognition.MetacognitionHook` |
| Watchdogs | `orqest.healing.{StallDetector,LoopDetector,RegressionDetector}` |
| Recovery actions | `orqest.healing.{RecoveryAction,WatchdogHook,default_policy}` |
| Model fallback | `orqest.healing.{FallbackModel,resolve_model_with_fallback}` |
| Healing lifecycle | `orqest.healing.HealingRunner` |
| UI components | `orqest.ui.{UIComponentSpec,ComponentRegistry,UIEmitter}` |
| First-party UI | `orqest.ui.components.*` |
| Plan tracking | `orqest.plan.{ExecutionPlan,PlanTask}` |
| Workbench bundle | `orqest.workbench.Workbench` |
| Web tools | `orqest.tools.web.{web_search,web_fetch}` |
| Model resolution | `orqest.utils.llm_model.resolve_model` |

---

## Section 7 — When NOT to Add to Core

The litmus test, verbatim from VISION.md:

> "Core Orqest manages the **shape and flow** of intelligence; extensions manage the **matter and action** of the domain. Could a developer building a headless coding assistant use this without knowing what Polymath is? If no, it belongs in a consumer, not Orqest core."

Examples of features that belong in **consumers**, not core:

- **Polymath's takeover dialog logic.** The `TakeoverDialogComponent` *spec* is core (shape); the rendering, modal styling, and confirm/input/choice handling are consumer (matter).
- **A consumer's domain-specific tool registry** (CFD simulation tools, clinical decision support, financial trading, etc.). `ToolRegistry` is core; the registry contents are the consumer's.
- **OTel exporter.** EventBus + AgentEvent are core (shape); the OTel exporter that subscribes to the bus and forwards spans/metrics to a collector is a third-party `orqest-otel-exporter` package (matter).
- **Durable execution / workflow engine.** Orqest is explicitly **not** a workflow engine. Persistence of agent runs across crashes belongs in a consumer that wants that resilience cost (e.g., Polymath using Postgres) — not in core.
- **Eval harness.** Metrics, replay, golden trajectories are observability tools, not cognitive primitives. Belongs in `orqest.eval` as a separate package, not in core.
- **Production memory backends (pgvector, Pinecone, Qdrant).** The `MemoryStore` Protocol is core (shape); concrete network-backed implementations are extensions or third-party packages.

When in doubt, apply the litmus test. If the feature would force a consumer in a different domain to learn yours to use Orqest, the feature belongs in a consumer.
